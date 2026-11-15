"""Background work (E1) on Arq/Redis - never inside web requests.

* scout_all (cron): each user's saved searches at the configured interval (GigSim 10 min, live 180 min - RUNBOOK.md),
  polite (rate-limited MCP), de-duplicated, and capped per run.
* analyze_job / resume_bid / conversation: graph runs. Arq job ids are deterministic (`analyze:<user>:<job>`), so a job is
  never queued twice; the graph itself resumes from its Postgres checkpoint, and writes use idempotency keys - a worker
  restart never double-analyses or double-submits.
* reconcile (startup + cron): re-enqueue runs that were in flight when a worker died, and degraded jobs once the
  marketplace is back.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from agent import runtime
from agent.nodes.scout import scout
from common import config as cfg
from common import db
from common.pii import setup_logging

MAX_NEW_PER_SCOUT = int(os.environ.get("MAX_NEW_PER_SCOUT", "8"))


async def startup(ctx: dict[str, Any]) -> None:
    setup_logging()
    await db.init_schema()
    await runtime.persistence()
    await reconcile(ctx)


async def analyze_job(ctx, user_id: str, job_id: str, force_bid: bool = False, run_id: str | None = None) -> dict:
    return await runtime.run_bid(user_id, job_id, force_bid=force_bid, run_id=run_id)


async def resume_bid(ctx, user_id: str, job_id: str, decision: dict, run_id: str | None = None) -> dict:
    await db.execute("UPDATE runs SET resume=%s WHERE run_id=%s", db.J(decision), run_id) if run_id else None
    return await runtime.run_bid(user_id, job_id, resume=decision, run_id=run_id)


async def conversation(ctx, user_id: str, thread_id: str, resume: dict | None = None, run_id: str | None = None) -> dict:
    return await runtime.run_conversation(user_id, thread_id, resume=resume, run_id=run_id)


async def regenerate_paragraph(ctx, user_id: str, job_id: str, paragraph: str, instruction: str) -> dict:
    from agent.nodes.writer import evidence_block
    from common.llm import chat
    from rag import verify

    g = await runtime.graph("bid")
    st = (await g.aget_state({"configurable": {"thread_id": f"bid:{user_id}:{job_id}"}})).values
    r = await chat("writer", "rewrite_paragraph", max_tokens=250, paragraph=paragraph, instruction=instruction or "make it more specific",
                   evidence=evidence_block(st.get("evidence", [])), title=st.get("job", {}).get("title", ""))
    text = r.text.strip()
    pool = [{**e, "text": e.get("snippet", "")} for e in st.get("evidence", [])]
    clean, removed = verify.apply(text, verify.verify_claims(text, pool))
    return {"paragraph": clean or paragraph, "removed_claims": [x["text"] for x in removed], "usage": r.usage("writer")}


async def replay_from(ctx, user_id: str, job_id: str, checkpoint_id: str) -> dict:
    """Re-run a job's thread from any checkpoint (C6). Forks the thread history; idempotency keys keep writes exactly-once."""
    user = await runtime.user_ctx(user_id)
    g = await runtime.graph("bid")
    tb = await runtime.toolbox(user)
    from common.tracing import new_trace_id, run_config

    tid = new_trace_id()
    cfg = run_config(f"bid:{user_id}:{job_id}", tid, user_id, toolbox=tb)
    cfg["configurable"]["checkpoint_id"] = checkpoint_id
    run_id = str(uuid.uuid4())
    await db.execute("INSERT INTO runs (run_id, user_id, kind, thread_id, job_id, status, trace_id) VALUES (%s,%s,'replay',%s,%s,'running',%s)",
                     run_id, user_id, f"bid:{user_id}:{job_id}", job_id, tid)
    async for ev in g.astream(None, cfg, stream_mode="updates"):
        for node, upd in ev.items():
            await db.execute("INSERT INTO run_events (run_id, node, data) VALUES (%s,%s,%s)", run_id, node, db.J(runtime._summ(node, upd)))
    await db.execute("UPDATE runs SET status='replayed', finished_at=now() WHERE run_id=%s", run_id)
    await db.execute("INSERT INTO run_events (run_id, node, data) VALUES (%s,'__end__',%s)", run_id, db.J({"status": "replayed"}))
    return {"run_id": run_id}


async def scout_user(ctx, user_id: str) -> dict:
    user = await runtime.user_ctx(user_id)
    searches = user.get("saved_searches") or []
    if not searches:
        return {"new": 0}
    tb = await runtime.toolbox(user)
    seen = {r["job_id"] for r in await db.fetch("SELECT job_id FROM seen_jobs WHERE user_id=%s", user_id)}
    recent = [{"job_id": r["job_id"], "title": r["title"] or "", "snippet": ""} for r in
              await db.fetch("SELECT job_id, title FROM jobs WHERE user_id=%s ORDER BY created_at DESC LIMIT 300", user_id)]
    from agent.nodes.scout import shingles

    for r in recent:
        r["_sh"] = shingles(r["title"])
    cur = await db.fetchone("SELECT last_scout_at FROM cursors WHERE user_id=%s", user_id)
    res = await scout(tb, searches, seen, recent, posted_after=0.0 if not cur else 0.0)
    for jid, dup in res["duplicates"]:
        await db.execute("INSERT INTO seen_jobs (user_id, job_id, dup_of) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", user_id, jid, dup)
        await db.execute("INSERT INTO jobs (user_id, job_id, title, status, dup_of) VALUES (%s,%s,%s,'duplicate',%s) ON CONFLICT DO NOTHING",
                         user_id, jid, next((j["title"] for j in recent if j["job_id"] == jid), ""), dup)
    queued = 0
    for j in res["new"]:
        await db.execute("INSERT INTO seen_jobs (user_id, job_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", user_id, j["job_id"])
        if queued >= MAX_NEW_PER_SCOUT:
            continue
        await db.execute("INSERT INTO jobs (user_id, job_id, title, status, connects_cost) VALUES (%s,%s,%s,'queued',%s) ON CONFLICT DO NOTHING",
                         user_id, j["job_id"], j["title"], j.get("connects_cost"))
        await ctx["redis"].enqueue_job("analyze_job", user_id, j["job_id"], _job_id=f"analyze:{user_id}:{j['job_id']}")
        queued += 1
    await db.execute("INSERT INTO cursors (user_id, last_scout_at) VALUES (%s,%s) ON CONFLICT (user_id) DO UPDATE SET last_scout_at=%s",
                     user_id, time.time(), time.time())
    return {"new": len(res["new"]), "queued": queued, "duplicates": len(res["duplicates"])}


async def scout_all(ctx) -> None:
    interval = cfg.get(f"marketplace.scout_interval_minutes.{cfg.get('marketplace.mode')}", 10) * 60
    for u in await db.fetch("SELECT u.id::text AS id, c.last_scout_at FROM users u JOIN user_settings s ON s.user_id=u.id "
                            "LEFT JOIN cursors c ON c.user_id=u.id WHERE s.onboarding_done"):
        if time.time() - float(u["last_scout_at"] or 0) >= interval:
            await ctx["redis"].enqueue_job("scout_user", u["id"], _job_id=f"scout:{u['id']}:{int(time.time() // interval)}")


async def sync_all(ctx) -> None:
    for u in await db.fetch("SELECT DISTINCT user_id::text AS id FROM pipeline"):
        try:
            res = await runtime.sync_pipeline(u["id"])
        except Exception as e:  # marketplace down: try next minute
            print("sync failed", u["id"], type(e).__name__)
            continue
        for th in res["new_threads"]:
            await ctx["redis"].enqueue_job("conversation", u["id"], th, None, str(uuid.uuid4()), _job_id=f"conv:{u['id']}:{th}:{int(time.time() // 60)}")


async def reconcile(ctx) -> None:
    # runs that were in flight when a worker died -> continue from checkpoint (idempotent writes make this safe)
    for r in await db.fetch("SELECT run_id::text, user_id::text, kind, job_id, thread_id, resume FROM runs WHERE status='running' "
                            "AND started_at < now() - interval '15 seconds'"):
        if r["kind"] == "bid" and r["job_id"]:
            await db.execute("UPDATE runs SET status='requeued' WHERE run_id=%s", r["run_id"])
            await ctx["redis"].enqueue_job("analyze_job", r["user_id"], r["job_id"], False, str(uuid.uuid4()),
                                           _job_id=f"recover:{r['run_id']}")
    # degraded jobs: retry once the marketplace is reachable again
    for j in await db.fetch("SELECT user_id::text, job_id FROM jobs WHERE status='queued_degraded' AND updated_at < now() - interval '30 seconds'"):
        await ctx["redis"].enqueue_job("analyze_job", j["user_id"], j["job_id"], _job_id=f"retry:{j['user_id']}:{j['job_id']}:{int(time.time() // 60)}")


class WorkerSettings:
    functions = [analyze_job, resume_bid, conversation, scout_user, regenerate_paragraph, replay_from]
    cron_jobs = [cron(scout_all, minute=set(range(0, 60, 2)), run_at_startup=False),
                 cron(sync_all, minute=set(range(60)), second={15}),
                 cron(reconcile, minute=set(range(0, 60, 2)), second={40})]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:16379/0"))
    max_jobs = int(os.environ.get("WORKER_MAX_JOBS", "2"))
    job_timeout = 1800
    keep_result = 3600
    max_tries = 3
