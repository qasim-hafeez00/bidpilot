from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api.auth.security import CurrentUser
from apps.api.queue import pool
from common import db
from common.tracing import trace_url

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
async def list_runs(job_id: str | None = None, user=CurrentUser):
    sql = ("SELECT run_id::text, kind, thread_id, job_id, status, started_at, finished_at, latency_s, tokens_in, tokens_out, usd, trace_id "
           "FROM runs WHERE user_id=%s")
    args: list = [user["id"]]
    if job_id:
        sql += " AND job_id=%s"
        args.append(job_id)
    return await db.fetch(sql + " ORDER BY started_at DESC LIMIT 100", *args)


@router.get("/{run_id}")
async def get_run(run_id: str, user=CurrentUser):
    r = await db.fetchone("SELECT run_id::text, kind, thread_id, job_id, status, started_at, finished_at, latency_s, tokens_in, tokens_out, usd, "
                          "trace_id, error FROM runs WHERE run_id=%s AND user_id=%s", run_id, user["id"])
    if not r:
        raise HTTPException(404, "run not found")
    ev = await db.fetch("SELECT id, node, data, ts FROM run_events WHERE run_id=%s ORDER BY id", run_id)
    return {**r, "trace_url": trace_url(r["trace_id"]) if r["trace_id"] else None, "events": ev}


@router.get("/history/{job_id}")
async def history(job_id: str, user=CurrentUser):
    """Checkpoint history of a job's thread: every node boundary can be replayed (C6)."""
    from agent import runtime

    g = await runtime.graph("bid")
    out = []
    async for snap in g.aget_state_history({"configurable": {"thread_id": f"bid:{user['id']}:{job_id}"}}):
        out.append({"checkpoint_id": snap.config["configurable"]["checkpoint_id"], "next": list(snap.next),
                    "status": snap.values.get("status"), "step": snap.metadata.get("step"), "created_at": snap.created_at})
    return out


@router.post("/replay/{job_id}/{checkpoint_id}")
async def replay(job_id: str, checkpoint_id: str, user=CurrentUser):
    """Fork the thread at a checkpoint and re-run from that node (writes stay idempotent)."""
    p = await pool()
    await p.enqueue_job("replay_from", user["id"], job_id, checkpoint_id, _job_id=f"replay:{user['id']}:{job_id}:{checkpoint_id}")
    return {"queued": True}
