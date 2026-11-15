"""Live Upwork adapter (A4): the official Upwork MCP server over Streamable HTTP via MultiServerMCPClient.

* OAuth 2.1 access token per user (obtained by apps/api/auth/upwork_oauth.py, stored encrypted, never logged).
* Tool names are mapped onto the port by agent/config.yaml `marketplace.upwork_tool_map`; the mapping is validated
  against `list_tools` at connect time and missing tools put the adapter in degraded mode instead of guessing.
* Live mode NEVER submits: `submit_proposal` only creates a draft; the user confirms on Upwork.
* No browser automation, no cookies, no scraping - only the MCP server's own tools.
"""
from __future__ import annotations

import json
import os
from typing import Any

from agent.marketplace_port import MarketplaceError, MarketplaceUnavailable
from common import config as cfg

UPWORK_MCP_URL = os.environ.get("UPWORK_MCP_URL", "https://mcp.upwork.com/mcp")


class UpworkLiveAdapter:
    name = "upwork_live"
    supports_submit = False

    def __init__(self, access_token: str | None, url: str = UPWORK_MCP_URL):
        if not access_token:
            raise MarketplaceUnavailable("Upwork account not connected (no OAuth token). Connect it in Settings.")
        self.url, self.token = url, access_token
        self.tool_map: dict[str, str] = dict(cfg.get("marketplace.upwork_tool_map", {}))
        self._tools: dict[str, Any] | None = None

    def _client(self):
        from langchain_mcp_adapters.client import MultiServerMCPClient

        return MultiServerMCPClient({"upwork": {"transport": "streamable_http", "url": self.url,
                                                "headers": {"Authorization": f"Bearer {self.token}"}}})

    async def _tools_by_name(self) -> dict[str, Any]:
        if self._tools is None:
            try:
                tools = await self._client().get_tools(server_name="upwork")
            except Exception as e:
                raise MarketplaceUnavailable(f"Upwork MCP unreachable: {type(e).__name__}") from e
            self._tools = {t.name: t for t in tools}
            missing = [f"{port}->{remote}" for port, remote in self.tool_map.items() if remote not in self._tools]
            if missing:
                self.missing = missing
        return self._tools

    async def _call(self, port_method: str, args: dict[str, Any]) -> dict[str, Any]:
        tools = await self._tools_by_name()
        remote = self.tool_map.get(port_method)
        if not remote or remote not in tools:
            raise MarketplaceError(f"live mode: Upwork MCP exposes no tool for '{port_method}' (mapped to '{remote}')")
        try:
            out = await tools[remote].ainvoke(args)
        except Exception as e:
            raise MarketplaceUnavailable(f"Upwork tool {remote} failed: {type(e).__name__}") from e
        if isinstance(out, str):
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                return {"text": out}
        return out if isinstance(out, dict) else {"result": out}

    async def search_jobs(self, query: str, skills=None, posted_after: float = 0.0, limit: int = 20):
        return await self._call("search_jobs", {"query": query, "limit": limit})

    async def get_job(self, job_id: str):
        return await self._call("get_job", {"job_id": job_id})

    async def get_client_history(self, client_id: str):
        return await self._call("get_client_history", {"client_id": client_id})

    async def get_connects_balance(self):
        return await self._call("get_connects_balance", {})

    async def get_market_stats(self, domain: str, kind: str):
        # Upwork exposes no market statistics tool; fall back to the historical job stream statistics shipped with BidPilot
        stats = json.loads((cfg.ROOT / "data" / "gigsim_seed" / "market_stats.json").read_text())
        return {"bucket": f"{domain}:{kind}", **stats.get(f"{domain}:{kind}", stats["other:hourly"]), "source": "bundled historical stats"}

    async def list_messages(self, thread_id: str | None = None):
        return await self._call("list_messages", {"thread_id": thread_id} if thread_id else {})

    async def list_events(self, after_id: int = 0):
        return {"events": []}  # live mode: pipeline updated from list_messages / proposals instead

    async def list_proposals(self):
        return {"proposals": []}

    async def create_proposal_draft(self, payload: dict[str, Any], idempotency_key: str):
        return {**await self._call("create_proposal_draft", {**payload, "idempotency_key": idempotency_key}),
                "status": "draft", "note": "Confirm this draft on Upwork - BidPilot never submits in live mode."}

    async def submit_proposal(self, proposal_id: str, idempotency_key: str):
        return {"proposal_id": proposal_id, "status": "draft_awaiting_user_confirmation_on_upwork", "connects_spent": 0}

    async def send_message(self, thread_id: str, text: str, idempotency_key: str):
        return {**await self._call("send_message", {"thread_id": thread_id, "text": text}), "status": "draft"}

    async def health(self):
        try:
            await self._tools_by_name()
            return {"ok": True, "missing_tools": getattr(self, "missing", [])}
        except Exception as e:
            return {"ok": False, "error": str(e)}
