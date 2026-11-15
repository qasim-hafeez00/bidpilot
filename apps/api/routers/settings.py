from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from apps.api.auth.security import CurrentUser
from apps.api.schemas import Health, MemoryItem, Settings
from common import db

router = APIRouter(prefix="/api", tags=["settings"])


@router.put("/settings", response_model=Settings)
async def put_settings(body: Settings, user=CurrentUser):
    await db.execute("UPDATE user_settings SET hourly_floor=%s, min_fixed=%s, weekly_connects_budget=%s, autonomy=%s, saved_searches=%s, "
                     "marketplace_mode=%s WHERE user_id=%s", body.hourly_floor, body.min_fixed, body.weekly_connects_budget, body.autonomy,
                     json.dumps([s.model_dump() for s in body.saved_searches]), body.marketplace_mode, user["id"])
    return body


@router.get("/accounts")
async def accounts(user=CurrentUser):
    rows = await db.fetch("SELECT provider, updated_at, expires_at, scope FROM credentials WHERE user_id=%s", user["id"])
    return {"connected": [{"provider": r["provider"], "updated_at": r["updated_at"], "expires_at": r["expires_at"], "scope": r["scope"]} for r in rows]}


@router.get("/memory", response_model=list[MemoryItem])
async def memory(user=CurrentUser):
    from agent import runtime
    from agent.memory.store import list_memory

    _, store = await runtime.persistence()
    return [MemoryItem(**m) for m in await list_memory(store, user["id"])]


@router.delete("/memory/{namespace}/{key}")
async def forget(namespace: str, key: str, user=CurrentUser):
    from agent import runtime
    from agent.memory.store import delete_memory

    _, store = await runtime.persistence()
    try:
        await delete_memory(store, user["id"], namespace, key)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"deleted": f"{namespace}/{key}"}


@router.get("/pipeline")
async def pipeline(user=CurrentUser):
    return await db.fetch("SELECT proposal_id, job_id, title, stage, thread_id, category, connects_spent, bid, updated_at FROM pipeline "
                          "WHERE user_id=%s ORDER BY updated_at DESC", user["id"])


@router.get("/health/dependencies", response_model=Health)
async def dependencies(user=CurrentUser):
    import asyncio

    from agent import runtime

    details: dict = {}
    state = "unknown"
    try:
        u = await runtime.user_ctx(user["id"])
        tb = await runtime.toolbox(u)
        await asyncio.wait_for(tb.call("pipeline", "list_proposals", {}, retries=0), timeout=6)
        state = "up"
        details = tb.status()
    except Exception as e:
        state = "down"
        details = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    q = await db.fetchone("SELECT COUNT(*) AS n FROM jobs WHERE user_id=%s AND status='queued_degraded'", user["id"])
    return Health(api="up", marketplace=state, details=details, queued_degraded=int(q["n"]))
