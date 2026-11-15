"""Graph runtime shared by the worker (and the API for reads): Postgres checkpointer + store, per-user MCP toolboxes,
run bookkeeping and node-by-node event persistence (the SSE stream reads these rows, so a refresh never loses state)."""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any

from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.mcp_client import ToolBox
from agent.memory import promotion_rules as pr
from agent.memory.store import record_outcome
from common import db
from common.secrets import decrypt
from common.tracing import new_trace_id, run_config, trace_url

_saver = _store = None
_graphs: dict[str, Any] = {}
_toolboxes: dict[str, ToolBox] = {}
_tb_lock = asyncio.Lock()


async def persistence():
    global _saver, _store
    if _saver is None:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore

        pool = AsyncConnectionPool(db.dsn(), min_size=1, max_size=6, open=False,
                                   kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
        await pool.open()
        _saver, _store = AsyncPostgresSaver(pool), AsyncPostgresStore(pool)
        await _saver.setup()
        await _store.setup()
    return _saver, _store


async def graph(kind: str):
    if kind not in _graphs:
        saver, store = await persistence()
        _graphs[kind] = (build_bid_graph if kind == "bid" else build_conversation_graph)(saver, store)
    return _graphs[kind]


async def user_ctx(user_id: str) -> dict[str, Any]:
    u = await db.fetchone("SELECT u.id::text AS id, u.persona, u.email, s.* FROM users u JOIN user_settings s ON s.user_id=u.id WHERE u.id=%s", user_id)
    if not u:
        raise KeyError(f"unknown user {user_id}")
    creds = {r["provider"]: decrypt(r["enc_access"]) for r in await db.fetch("SELECT provider, enc_access FROM credentials WHERE user_id=%s", user_id)}
    u["gigsim_token"] = creds.get("gigsim")
    u["upwork_token"] = creds.get("upwork")
    u["settings"] = {"hourly_floor": float(u["hourly_floor"]), "min_fixed": float(u["min_fixed"]),
                     "weekly_connects_budget": int(u["weekly_connects_budget"]), "autonomy": u["autonomy"]}
    spent = await db.fetchone("SELECT COALESCE(SUM(connects_spent),0) AS s FROM pipeline WHERE user_id=%s AND updated_at > now() - interval '7 days'", user_id)
    u["settings"]["connects_spent_this_week"] = int(spent["s"])
    return u


async def toolbox(user: dict[str, Any]) -> ToolBox:
    key = f"{user['id']}:{user['persona']}"
    async with _tb_lock:
        tb = _toolboxes.get(key)
        if tb is None:
            if os.environ.get("MCP_TRANSPORT") == "memory":  # single small container (free hosting): servers in-process
                from agent.mcp_client import InMemoryToolBox

                tb = await InMemoryToolBox(user["id"], user["persona"], user.get("gigsim_token")).start()
            else:
                tb = await ToolBox(user["id"], user["persona"], user.get("gigsim_token"), user.get("upwork_token")).start()
            _toolboxes[key] = tb
        return tb


async def dependency_status() -> dict[str, Any]:
    out = {}
    for key, tb in _toolboxes.items():
        out[key] = tb.status()
    return out


def _summ(node: str, upd: Any) -> dict[str, Any]:
    if not isinstance(upd, dict):
        return {"node": node}
    t = (upd.get("trace") or [{}])[-1]
    return {"node": node, "status": upd.get("status"), "trace": {k: v for k, v in t.items() if k not in ("ts",)},
            "usage": upd.get("usage"), "attention": upd.get("attention_reason")}


async def _run(kind: str, user: dict[str, Any], thread_id: str, inp: Any, run_id: str, job_id: str | None) -> dict[str, Any]:
    g = await graph(kind)
    tb = await toolbox(user)
    trace_id = new_trace_id()
    cfg = run_config(thread_id, trace_id, user["id"], toolbox=tb)
    await db.execute("INSERT INTO runs (run_id, user_id, kind, thread_id, job_id, status, trace_id) VALUES (%s,%s,%s,%s,%s,'running',%s) "
                     "ON CONFLICT (run_id) DO UPDATE SET status='running', trace_id=EXCLUDED.trace_id", run_id, user["id"], kind,
                     thread_id, job_id, trace_id)
    t0 = time.perf_counter()
    try:
        async for ev in g.astream(inp, cfg, stream_mode="updates"):
            for node, upd in ev.items():
                data = {"node": node, "interrupt": True} if node == "__interrupt__" else _summ(node, upd)
                await db.execute("INSERT INTO run_events (run_id, node, data) VALUES (%s,%s,%s)", run_id, node, db.J(data))
        err = None
    except Exception as e:  # graph-level failure -> dead letter for this run
        err = f"{type(e).__name__}: {e}"[:1000]
        await db.execute("INSERT INTO run_events (run_id, node, data) VALUES (%s,'error',%s)", run_id, db.J({"error": err}))
    st = (await g.aget_state(cfg)).values
    usage = [u for u in st.get("usage", []) if isinstance(u, dict)]
    tin, tout = sum(int(u.get("in", 0)) for u in usage), sum(int(u.get("out", 0)) for u in usage)
    usd = sum(float(u.get("usd", 0)) for u in usage)
    status = "dead_letter" if err else st.get("status", "done")
    await db.execute("UPDATE runs SET status=%s, finished_at=now(), latency_s=%s, tokens_in=%s, tokens_out=%s, usd=%s, error=%s WHERE run_id=%s",
                     status, time.perf_counter() - t0, tin, tout, usd, err, run_id)
    await db.execute("INSERT INTO run_events (run_id, node, data) VALUES (%s,'__end__',%s)", run_id,
                     db.J({"status": status, "trace_url": trace_url(trace_id), "trace_id": trace_id}))
    return {"state": st, "status": status, "trace_id": trace_id, "error": err}


async def run_bid(user_id: str, job_id: str, resume: dict[str, Any] | None = None, force_bid: bool = False,
                  run_id: str | None = None) -> dict[str, Any]:
    user = await user_ctx(user_id)
    thread = f"bid:{user_id}:{job_id}" + (":forced" if force_bid else "")
    run_id = run_id or str(uuid.uuid4())
    if resume is not None:
        inp: Any = Command(resume=resume)
    else:
        g = await graph("bid")
        existing = await g.aget_state({"configurable": {"thread_id": thread}})
        if existing and existing.next:  # crashed / interrupted mid-run: continue from the checkpoint, never restart
            inp = None
        else:
            inp = {"job_id": job_id, "user_id": user_id, "persona": user["persona"],
                   "settings": {**user["settings"], "force_bid": force_bid}}
    await db.execute("INSERT INTO jobs (user_id, job_id, status, thread_id) VALUES (%s,%s,'analyzing',%s) ON CONFLICT (user_id, job_id) "
                     "DO UPDATE SET status=CASE WHEN jobs.status IN ('awaiting_approval') AND %s THEN 'submitting' ELSE "
                     "CASE WHEN %s THEN jobs.status ELSE 'analyzing' END END, thread_id=EXCLUDED.thread_id, updated_at=now()",
                     user_id, job_id, thread, resume is not None, resume is not None)
    res = await _run("bid", user, thread, inp, run_id, job_id)
    await persist_job(user_id, job_id, thread, res)
    return {"run_id": run_id, "status": res["status"], "trace_id": res["trace_id"]}


async def persist_job(user_id: str, job_id: str, thread: str, res: dict[str, Any]) -> None:
    st = res["state"]
    job, fit, risk, dec = st.get("job", {}), st.get("fit_report", {}), st.get("risk_report", {}), st.get("decision", {})
    from common.skills import skill_domain

    cat = skill_domain((job.get("skills") or ["?"])[0])
    await db.execute(
        "UPDATE jobs SET title=%s, data=%s, status=%s, fit=%s, risk=%s, decision=%s, price=%s, connects_cost=%s, risk_flags=%s, "
        "trace_id=%s, category=%s, updated_at=now() WHERE user_id=%s AND job_id=%s",
        job.get("title"), db.J({k: job.get(k) for k in ("title", "description", "skills", "is_hourly", "budget", "hourly_low",
                                                        "hourly_high", "client_summary", "screening_questions", "posted_at", "client_id")}),
        res["status"], fit.get("score"), risk.get("score"), dec.get("action"), db.J(st.get("price_quote")), job.get("connects_cost"),
        db.J(risk.get("flags", [])), res["trace_id"], cat, user_id, job_id)
    sub = st.get("submission")
    if sub and res["status"] in ("submitted", "draft_on_marketplace"):
        draft = st["drafts"][-1]
        await db.execute("INSERT INTO pipeline (user_id, proposal_id, job_id, title, stage, category, opening_style, connects_spent, bid) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id, proposal_id) DO NOTHING",
                         user_id, sub["proposal_id"], job_id, job.get("title"), "submitted" if res["status"] == "submitted" else "drafted",
                         cat, pr.opening_style(draft["cover_letter"]), int(sub.get("connects_spent") or 0), db.J(st.get("price_quote")))
    for a in st.get("approvals", [])[-1:]:
        await db.execute("INSERT INTO approvals_log (user_id, thread_id, kind, action, reason, diff) SELECT %s,%s,'proposal',%s,%s,%s "
                         "WHERE NOT EXISTS (SELECT 1 FROM approvals_log WHERE user_id=%s AND thread_id=%s AND action=%s AND COALESCE(reason,'')=COALESCE(%s,''))",
                         user_id, thread, a["action"], a.get("reason"), db.J((st.get("drafts") or [{}])[-1].get("diff")),
                         user_id, thread, a["action"], a.get("reason"))


async def run_conversation(user_id: str, thread_id: str, resume: dict[str, Any] | None = None, run_id: str | None = None) -> dict[str, Any]:
    user = await user_ctx(user_id)
    conv = await db.fetchone("SELECT * FROM conversations WHERE user_id=%s AND thread_id=%s", user_id, thread_id)
    gthread = f"conv:{user_id}:{thread_id}:{int(conv['last_message_at'].timestamp()) if conv and conv.get('last_message_at') else 0}"
    run_id = run_id or str(uuid.uuid4())
    if resume is not None:
        inp: Any = Command(resume=resume)
    else:
        pipe = await db.fetchone("SELECT bid FROM pipeline WHERE user_id=%s AND thread_id=%s", user_id, thread_id)
        inp = {"thread_id": thread_id, "user_id": user_id, "persona": user["persona"], "job_id": conv.get("job_id") if conv else None,
               "settings": user["settings"], "bid": json.dumps((pipe or {}).get("bid") or {})}
    await db.execute("UPDATE conversations SET graph_thread=%s, status='drafting' WHERE user_id=%s AND thread_id=%s", gthread, user_id, thread_id)
    res = await _run("conversation", user, gthread, inp, run_id, conv.get("job_id") if conv else None)
    st = res["state"]
    await db.execute("UPDATE conversations SET status=%s, intent=%s WHERE user_id=%s AND thread_id=%s", res["status"],
                     (st.get("intent") or {}).get("intent"), user_id, thread_id)
    return {"run_id": run_id, "status": res["status"], "trace_id": res["trace_id"]}


STAGE = {"submitted": "submitted", "viewed": "viewed", "replied": "replied", "interview_requested": "replied", "message": None,
         "interview": "interview", "hired": "hired", "lost": "lost", "not_selected": "lost"}
ORDER = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]


async def sync_pipeline(user_id: str) -> dict[str, Any]:
    """Poll marketplace events (read tool) -> pipeline stages, new conversations, outcome memory."""
    user = await user_ctx(user_id)
    tb = await toolbox(user)
    cur = await db.fetchone("SELECT last_event_id FROM cursors WHERE user_id=%s", user_id)
    after = int(cur["last_event_id"]) if cur else 0
    evs = (await tb.call("pipeline", "list_events", {"after_id": after})).get("events", [])
    _, store = await persistence()
    new_threads = []
    for e in evs:
        stage = STAGE.get(e["type"])
        row = await db.fetchone("SELECT * FROM pipeline WHERE user_id=%s AND proposal_id=%s", user_id, e.get("proposal_id"))
        if row and stage and ORDER.index(stage) > ORDER.index(row["stage"]) or (row and stage == "lost" and row["stage"] != "hired"):
            await db.execute("UPDATE pipeline SET stage=%s, thread_id=COALESCE(%s, thread_id), updated_at=now() WHERE user_id=%s AND proposal_id=%s",
                             stage, e.get("thread_id"), user_id, e["proposal_id"])
            if stage in ("replied", "lost") and row["stage"] in ("submitted", "viewed"):
                await record_outcome(store, user_id, row["category"] or "other", row["opening_style"] or "problem_first", stage == "replied")
            if stage == "hired":
                await record_outcome(store, user_id, row["category"] or "other", row["opening_style"] or "problem_first", True, True)
        if e.get("thread_id") and e["type"] in ("replied", "interview_requested", "message"):
            await db.execute("INSERT INTO conversations (user_id, thread_id, proposal_id, job_id, title, last_message_at, status) "
                             "VALUES (%s,%s,%s,%s,%s,to_timestamp(%s),'new') ON CONFLICT (user_id, thread_id) DO UPDATE SET "
                             "last_message_at=EXCLUDED.last_message_at, status='new'", user_id, e["thread_id"], e.get("proposal_id"),
                             (e.get("data") or {}).get("job_id") or (row or {}).get("job_id"), (row or {}).get("title"), e["ts"])
            new_threads.append(e["thread_id"])
        after = max(after, e["event_id"])
    await db.execute("INSERT INTO cursors (user_id, last_event_id) VALUES (%s,%s) ON CONFLICT (user_id) DO UPDATE SET last_event_id=%s",
                     user_id, after, after)
    return {"events": len(evs), "new_threads": sorted(set(new_threads))}
