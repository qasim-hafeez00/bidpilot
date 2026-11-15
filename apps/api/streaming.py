"""SSE bridge to LangGraph streams. The worker persists each `stream_mode="updates"` event to run_events; this endpoint
tails those rows, so several viewers and page refreshes all see the same live node-by-node progress."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from apps.api.auth.security import CurrentUser
from common import db

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/{run_id}/stream")
async def stream(run_id: str, request: Request, user=CurrentUser):
    run = await db.fetchone("SELECT status FROM runs WHERE run_id=%s AND user_id=%s", run_id, user["id"])
    if not run:
        raise HTTPException(404, "run not found")

    async def gen():
        last = 0
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            rows = await db.fetch("SELECT id, node, data, ts FROM run_events WHERE run_id=%s AND id>%s ORDER BY id", run_id, last)
            for r in rows:
                last = r["id"]
                yield {"event": "node", "id": str(r["id"]), "data": json.dumps({"node": r["node"], "ts": r["ts"].isoformat(), **(r["data"] or {})})}
                if r["node"] == "__end__":
                    yield {"event": "end", "data": json.dumps(r["data"])}
                    return
            idle = 0 if rows else idle + 1
            if idle % 20 == 19:
                yield {"event": "ping", "data": "{}"}
            await asyncio.sleep(0.5)

    return EventSourceResponse(gen())
