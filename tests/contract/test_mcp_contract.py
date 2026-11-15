"""MCP contract tests through the SDK's in-memory client.

* Schema snapshot: fails when any tool's name, input schema, output schema or annotations change unintentionally.
  Refresh deliberately with:  UPDATE_SNAPSHOTS=1 pytest tests/contract
* Annotations: write tools are idempotent and not read-only; submit/send are destructive; reads are read-only.
* Validation: Pydantic constraints reject bad arguments before any upstream call.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

SNAP = Path(__file__).parent / "snapshots" / "tools.json"
SERVERS = ["portfolio", "marketplace", "workspace"]


async def _tools(name: str):
    import importlib

    server = importlib.import_module(f"mcp_servers.{name}.server").mcp
    async with create_connected_server_and_client_session(server._mcp_server) as s:
        return (await s.list_tools()).tools


async def test_tool_schema_snapshot():
    current = {}
    for name in SERVERS:
        for t in await _tools(name):
            current[f"{name}.{t.name}"] = {"input": t.inputSchema, "output": t.outputSchema,
                                           "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else None}
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not SNAP.exists():
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(current, indent=1, sort_keys=True), encoding="utf-8")
    saved = json.loads(SNAP.read_text(encoding="utf-8"))
    assert sorted(saved) == sorted(current), "tool added/removed - update the snapshot deliberately"
    for k in saved:
        assert saved[k] == json.loads(json.dumps(current[k], sort_keys=True)), f"tool signature changed: {k}"


async def test_annotations():
    tools = {t.name: t for t in await _tools("marketplace")}
    for w in ("create_proposal_draft", "submit_proposal", "send_message"):
        a = tools[w].annotations
        assert a.readOnlyHint is False and a.idempotentHint is True
        assert "idempotency_key" in tools[w].inputSchema["required"]
        assert "dry_run" in tools[w].inputSchema["properties"]
    assert tools["submit_proposal"].annotations.destructiveHint is True
    assert tools["create_proposal_draft"].annotations.destructiveHint is False
    for r in ("search_jobs", "get_job", "get_client_history"):
        assert tools[r].annotations.readOnlyHint is True
    for t in await _tools("portfolio"):
        assert t.annotations.readOnlyHint is True


@pytest.mark.parametrize("args", [{"proposal_id": "pr-1", "idempotency_key": "short"},          # key too short
                                  {"proposal_id": "pr-1", "idempotency_key": "has spaces!!!!"}])  # bad chars
async def test_write_validation_rejects_bad_keys(args):
    from mcp_servers.marketplace.server import mcp

    async with create_connected_server_and_client_session(mcp._mcp_server) as s:
        r = await s.call_tool("submit_proposal", args)
        assert r.isError


async def test_workspace_round_trip_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DB", str(tmp_path / "ws.db"))
    from mcp_servers.workspace.server import mcp

    async with create_connected_server_and_client_session(mcp._mcp_server) as s:
        slots = (await s.call_tool("get_free_slots", {"start_date": "2026-11-16", "days": 3})).structuredContent
        assert slots["slots"]
        args = {"start": slots["slots"][0]["start"], "duration_min": 30, "title": "Interview", "idempotency_key": "hold-key-0001"}
        a = (await s.call_tool("create_interview_hold", args)).structuredContent
        b = (await s.call_tool("create_interview_hold", args)).structuredContent
        assert a["hold_id"] == b["hold_id"] and b["idempotent_replay"] is True
        again = (await s.call_tool("get_free_slots", {"start_date": "2026-11-16", "days": 3})).structuredContent
        assert again["slots"][0]["start"] != slots["slots"][0]["start"]


async def test_portfolio_search_finds_implied_skill_in_code(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_PERSONA", "fullstack")
    from mcp_servers.portfolio.server import mcp

    async with create_connected_server_and_client_session(mcp._mcp_server) as s:
        r = (await s.call_tool("search_evidence", {"requirement": "Celery background workers", "k": 5,
                                                   "filters": {"persona": "fullstack"}})).structuredContent
        assert any("Celery" in i["skills"] for i in r["items"])
        cs = (await s.call_tool("get_case_study", {"id": "fullstack:drf-api"})).structuredContent
        assert "310 ms" in cs["markdown"]
