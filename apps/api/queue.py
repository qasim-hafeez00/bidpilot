"""Enqueue background work on Arq (the API never runs graphs inside a request)."""
from __future__ import annotations

import os
import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from common import db

_pool: ArqRedis | None = None


async def pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:16379/0")))
    return _pool


async def enqueue(fn: str, *args, job_id: str | None = None, run_kind: str | None = None, user_id: str | None = None,
                  thread_id: str | None = None, job: str | None = None) -> str:
    """Creates the `runs` row first (status queued) so the UI can open the stream immediately."""
    run_id = str(uuid.uuid4())
    if run_kind:
        await db.execute("INSERT INTO runs (run_id, user_id, kind, thread_id, job_id, status) VALUES (%s,%s,%s,%s,%s,'queued')",
                         run_id, user_id, run_kind, thread_id or "", job)
    p = await pool()
    await p.enqueue_job(fn, *args, run_id, _job_id=job_id or f"{fn}:{run_id}")
    return run_id
