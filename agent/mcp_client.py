"""MultiServerMCPClient setup + per-agent tool allowlists + client discipline (A6).

* Each agent gets ONLY the tools it needs (ALLOWLIST, filtered by name).
* Timeouts, bounded retries with exponential backoff, and a typed degraded mode: if the marketplace server is down,
  calls raise MarketplaceUnavailable; the graph moves the job to `queued_degraded`, the UI shows a banner, and the
  worker retries later (see agent/graphs/bid_graph.py::_guard and worker/tasks.py).
* Persistent sessions (stdio subprocesses locally, Streamable HTTP + bearer JWT in docker / production).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from agent.marketplace_port import MarketplaceError, MarketplaceUnavailable
from common.secrets import mint_user_token

ALLOWLIST: dict[str, set[str]] = {
    "scout": {"search_jobs", "get_job"},
    "intake": {"get_job"},
    "analyst": set(),
    "risk_assessor": {"get_client_history"},
    "fit_matcher": {"search_evidence", "list_skills"},
    "pricing": {"get_market_stats", "get_connects_balance"},
    "writer": {"search_evidence", "get_case_study"},
    "verifier": {"search_evidence"},
    "critic": {"search_evidence", "get_case_study"},
    "compliance": set(),
    "approval": {"create_proposal_draft", "submit_proposal", "get_connects_balance"},  # dry_run previews only
    "submitter": {"create_proposal_draft", "submit_proposal"},                          # after human approval only
    "client_liaison": {"list_messages", "get_job", "get_free_slots", "search_evidence"},
    "liaison_sender": {"send_message", "create_interview_hold", "create_email_draft"},  # after approval only
    "pipeline": {"list_events", "list_proposals", "list_messages"},
}
TIMEOUTS = {"search_evidence": 90, "get_case_study": 30, "list_skills": 60}
SERVERS = ("portfolio", "marketplace", "workspace")


class ToolError(RuntimeError):
    pass


class ServerDown(MarketplaceUnavailable):
    pass


def connections(user_id: str, persona: str, gigsim_token: str | None, upwork_token: str | None = None) -> dict[str, dict]:
    jwt = mint_user_token(user_id, persona, gigsim_token, upwork_token)
    if os.environ.get("MCP_TRANSPORT", "stdio") == "http":
        urls = {"portfolio": os.environ.get("PORTFOLIO_MCP_URL", "http://localhost:8101/mcp"),
                "marketplace": os.environ.get("MARKETPLACE_MCP_URL", "http://localhost:8102/mcp"),
                "workspace": os.environ.get("WORKSPACE_MCP_URL", "http://localhost:8103/mcp")}
        return {k: {"transport": "streamable_http", "url": u, "headers": {"Authorization": f"Bearer {jwt}"}} for k, u in urls.items()}
    env = {**os.environ, "MCP_USER_JWT": jwt, "PYTHONWARNINGS": "ignore"}
    return {name: {"transport": "stdio", "command": sys.executable,
                   "args": ["-m", f"mcp_servers.{name}.server", "--transport", "stdio"], "env": env,
                   "cwd": str(__import__("common.config", fromlist=["ROOT"]).ROOT)} for name in SERVERS}


class ToolBox:
    """Long-lived MCP sessions for one user, with allowlists, timeouts, retries and health."""

    def __init__(self, user_id: str, persona: str, gigsim_token: str | None = None, upwork_token: str | None = None,
                 servers: tuple[str, ...] = SERVERS):
        self.user_id, self.persona = user_id, persona
        self.conns = {k: v for k, v in connections(user_id, persona, gigsim_token, upwork_token).items() if k in servers}
        self.sessions: dict[str, Any] = {}
        self.tool_server: dict[str, str] = {}
        self.down: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> ToolBox:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        self._client = MultiServerMCPClient(self.conns)
        self._owners: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}
        await asyncio.gather(*(self._connect(n) for n in self.conns))
        return self

    async def _owner(self, name: str, ready: asyncio.Future, stop: asyncio.Event) -> None:
        """Each session lives in its own task: anyio requires enter/exit in the same task."""
        try:
            async with self._client.session(name) as s:
                tools = await s.list_tools()
                if not ready.done():
                    ready.set_result((s, tools))
                await stop.wait()
        except BaseException as e:  # server died or failed to start
            if not ready.done():
                ready.set_exception(e if isinstance(e, Exception) else RuntimeError(repr(e)))
            self.sessions.pop(name, None)
            self.down[name] = f"{type(e).__name__}: {e}"[:200]

    async def _connect(self, name: str) -> None:
        old = getattr(self, "_owners", {}).pop(name, None)
        if old:
            old[1].set()
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        stop = asyncio.Event()
        task = asyncio.create_task(self._owner(name, ready, stop))
        self._owners[name] = (task, stop)
        try:
            s, tools = await asyncio.wait_for(ready, timeout=90)
            self.sessions[name] = s
            for t in tools.tools:
                self.tool_server[t.name] = name
            self.down.pop(name, None)
        except Exception as e:  # degraded, not fatal
            self.down[name] = f"{type(e).__name__}: {e}"[:200]
            self.sessions.pop(name, None)
            stop.set()

    async def close(self) -> None:
        for _task, stop in getattr(self, "_owners", {}).values():
            stop.set()
        for task, _ in getattr(self, "_owners", {}).values():
            try:
                await asyncio.wait_for(task, timeout=10)
            except BaseException:
                pass
        self.sessions.clear()

    async def __aenter__(self) -> ToolBox:
        return await self.start()

    async def __aexit__(self, *exc) -> None:
        await self.close()

    def status(self) -> dict[str, Any]:
        return {n: ("down: " + self.down[n]) if n in self.down else "up" for n in self.conns}

    async def call(self, agent: str, tool: str, args: dict[str, Any], trace_id: str | None = None,
                   retries: int = 2) -> dict[str, Any]:
        if tool not in ALLOWLIST.get(agent, set()):
            raise PermissionError(f"agent '{agent}' is not allowed to call tool '{tool}'")
        server = self.tool_server.get(tool) or ("marketplace" if tool in {"search_jobs", "get_job", "send_message"} else None)
        if trace_id:
            args = {**args, "trace_id": trace_id}
        delay = 0.5
        for attempt in range(retries + 1):
            if server not in self.sessions:
                async with self._lock:
                    if server in self.conns and server not in self.sessions:
                        await self._connect(server)
            sess = self.sessions.get(server)
            if sess is None:
                err: Exception = ServerDown(f"{server} MCP server unavailable: {self.down.get(server, 'not connected')}")
            else:
                try:
                    res = await asyncio.wait_for(sess.call_tool(tool, args), timeout=TIMEOUTS.get(tool, 30))
                    return _parse(tool, res)
                except (MarketplaceError, PermissionError, ToolError):
                    raise
                except MarketplaceUnavailable as e:
                    err = e
                except Exception as e:  # session broken (server killed) or timeout
                    err = ServerDown(f"{server}: {type(e).__name__}: {e}"[:300])
                    self.sessions.pop(server, None)
                    self.down[server] = str(err)
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
        raise err

    async def langchain_tools(self, agent: str | None = None):
        """LangChain tools bound to the live sessions (ReAct / supervisor baselines, R&D question A)."""
        from langchain_mcp_adapters.tools import load_mcp_tools

        out = []
        for s in self.sessions.values():
            for t in await load_mcp_tools(s):
                if agent is None or t.name in ALLOWLIST.get(agent, set()):
                    out.append(t)
        return out


def _parse(tool: str, res: Any) -> dict[str, Any]:
    text = " ".join(getattr(c, "text", "") for c in (res.content or []))
    if getattr(res, "isError", False):
        if "MARKETPLACE_UNAVAILABLE" in text:
            raise MarketplaceUnavailable(text)
        if "MARKETPLACE_ERROR" in text:
            raise MarketplaceError(text)
        raise ToolError(f"{tool}: {text[:400]}")
    if getattr(res, "structuredContent", None):
        sc = res.structuredContent
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


class InMemoryToolBox(ToolBox):
    """Same interface, but each MCP server runs in-process over the SDK's in-memory transport.

    Used by unit tests (A7: "unit tests through an in-memory MCP client") and by the evaluation runners, so they exercise
    the real MCP tool layer (schemas, validation, annotations, audit) without subprocess start-up cost.
    """

    def __init__(self, user_id: str, persona: str, gigsim_token: str | None = None, servers: tuple[str, ...] = SERVERS):
        self.user_id, self.persona, self.gigsim_token = user_id, persona, gigsim_token
        self.conns = {s: {} for s in servers}
        self.sessions, self.tool_server, self.down = {}, {}, {}
        self._lock = asyncio.Lock()

    async def start(self) -> InMemoryToolBox:
        from mcp_servers.common import identity

        self._ident_token = identity.set({"user_id": self.user_id, "persona": self.persona,
                                          "gigsim_token": self.gigsim_token, "upwork_token": None})
        self._owners = {}
        for name in self.conns:
            await self._connect(name)
        return self

    async def _owner(self, name: str, ready: asyncio.Future, stop: asyncio.Event) -> None:
        import importlib

        from mcp.shared.memory import create_connected_server_and_client_session

        try:
            server = importlib.import_module(f"mcp_servers.{name}.server").mcp
            async with create_connected_server_and_client_session(server._mcp_server) as s:
                tools = await s.list_tools()
                if not ready.done():
                    ready.set_result((s, tools))
                await stop.wait()
        except BaseException as e:
            if not ready.done():
                ready.set_exception(e if isinstance(e, Exception) else RuntimeError(repr(e)))
            self.sessions.pop(name, None)
            self.down[name] = f"{type(e).__name__}: {e}"[:200]
