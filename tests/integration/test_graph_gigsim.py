"""Integration: the bid graph against a running GigSim (GIGSIM_BASE_URL) with a Postgres checkpointer.

Proves C6: the process "crashes" while a proposal waits for approval (graph + checkpointer objects are discarded), a new
process approves from the persisted checkpoint, the proposal is submitted, and re-running the submit returns an
idempotent replay - Connects are spent exactly once.   Run:  pytest -m integration tests/integration
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest
from langgraph.types import Command

pytestmark = pytest.mark.integration


def _gigsim_up() -> bool:
    try:
        return httpx.get(os.environ.get("GIGSIM_BASE_URL", "http://localhost:18081") + "/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _gigsim_up(), reason="GigSim not running")
async def test_crash_and_resume_submits_exactly_once(monkeypatch):
    monkeypatch.setenv("LLM_DISABLED", "1")  # template writer: deterministic and fast
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from agent.graphs.bid_graph import build_bid_graph
    from agent.mcp_client import InMemoryToolBox
    from common.db import dsn
    from common.tracing import run_config

    job_id = os.environ.get("TEST_JOB_ID", "dda-0003-1c2c39")
    thread = f"it-{uuid.uuid4().hex[:8]}"
    settings = {"hourly_floor": 10, "min_fixed": 10, "force_bid": True}
    async with InMemoryToolBox("it-user", "data_analyst", "dev-token-data_analyst") as tb:
        cfg = run_config(thread, str(uuid.uuid4()), "it-user", toolbox=tb)
        async with AsyncPostgresSaver.from_conn_string(dsn()) as saver:
            await saver.setup()
            st = await build_bid_graph(saver).ainvoke({"job_id": job_id, "user_id": "it-user", "persona": "data_analyst", "settings": settings}, cfg)
            assert st["status"] == "awaiting_approval"
        # --- crash: everything above is gone; a fresh process resumes from Postgres ---
        async with AsyncPostgresSaver.from_conn_string(dsn()) as saver2:
            g2 = build_bid_graph(saver2)
            st2 = await g2.ainvoke(Command(resume={"action": "approve"}), cfg)
            assert st2["status"] == "submitted"
            first = st2["submission"]
            # a retried submit (e.g. worker died after the HTTP call) must be an idempotent replay
            from agent.nodes.approval import submit

            again = await submit(st2, cfg)
            assert again["submission"]["proposal_id"] == first["proposal_id"]
            assert again["submission"].get("idempotent_replay") is True
