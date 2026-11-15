"""GigSim adapter: REST client with bounded retries + backoff that honours Retry-After (429) and 5xx."""
from __future__ import annotations

import asyncio
import os
import random
from typing import Any

import httpx

from agent.marketplace_port import MarketplaceError, MarketplaceUnavailable


class GigSimAdapter:
    name = "gigsim"
    supports_submit = True

    def __init__(self, token: str, base_url: str | None = None, max_retries: int = 3, timeout: float = 15.0):
        self.base = (base_url or os.environ.get("GIGSIM_BASE_URL", "http://localhost:18081")).rstrip("/")
        self.token, self.max_retries, self.timeout = token, max_retries, timeout
        self.freelancer_id: str | None = None

    async def _req(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None,
                   idem: str | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}"}
        if idem:
            headers["Idempotency-Key"] = idem
        delay = 0.5
        last = ""
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as c:
                    r = await c.request(method, self.base + path, params=params, json=json, headers=headers)
            except httpx.HTTPError as e:
                last = f"network: {type(e).__name__}"
            else:
                if r.status_code < 400:
                    return r.json()
                if r.status_code == 429 or r.status_code >= 500:
                    last = f"{r.status_code}: {r.text[:200]}"
                    if r.status_code == 429:
                        delay = max(delay, float(r.headers.get("Retry-After", delay)))
                else:
                    try:
                        msg = r.json().get("error", r.text[:200])
                    except ValueError:
                        msg = r.text[:200]
                    raise MarketplaceError(f"{r.status_code}: {msg}")
            if attempt < self.max_retries:
                await asyncio.sleep(min(delay, 8) * (1 + random.random() * 0.25))
                delay *= 2
        raise MarketplaceUnavailable(f"gigsim unavailable after {self.max_retries + 1} attempts ({last})")

    async def _fid(self) -> str:
        # GigSim derives the freelancer from the token; the connects endpoint needs the id explicitly
        if not self.freelancer_id:
            self.freelancer_id = os.environ.get("GIGSIM_FREELANCER_ID") or _fid_from_token(self.token)
        return self.freelancer_id

    async def search_jobs(self, query: str, skills: list[str] | None = None, posted_after: float = 0.0, limit: int = 20):
        return await self._req("GET", "/v1/jobs", params={"q": query, "skills": ",".join(skills or []),
                                                          "posted_after": posted_after, "limit": limit})

    async def get_job(self, job_id: str):
        return await self._req("GET", f"/v1/jobs/{job_id}")

    async def get_client_history(self, client_id: str):
        return await self._req("GET", f"/v1/clients/{client_id}/history")

    async def get_connects_balance(self):
        return await self._req("GET", f"/v1/freelancers/{await self._fid()}/connects")

    async def get_market_stats(self, domain: str, kind: str):
        return await self._req("GET", "/v1/market/stats", params={"domain": domain, "kind": kind})

    async def list_messages(self, thread_id: str | None = None):
        return await self._req("GET", "/v1/messages", params={"thread_id": thread_id} if thread_id else None)

    async def list_events(self, after_id: int = 0):
        return await self._req("GET", "/v1/events", params={"after_id": after_id})

    async def list_proposals(self):
        return await self._req("GET", "/v1/proposals")

    async def create_proposal_draft(self, payload: dict[str, Any], idempotency_key: str):
        return await self._req("POST", "/v1/proposals", json=payload, idem=idempotency_key)

    async def submit_proposal(self, proposal_id: str, idempotency_key: str):
        return await self._req("POST", f"/v1/proposals/{proposal_id}/submit", idem=idempotency_key)

    async def send_message(self, thread_id: str, text: str, idempotency_key: str):
        return await self._req("POST", "/v1/messages", json={"thread_id": thread_id, "text": text}, idem=idempotency_key)

    async def get_policy(self):
        return await self._req("GET", "/v1/policy")

    async def health(self):
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(self.base + "/health")
            return {"ok": r.status_code == 200, **r.json()}
        except httpx.HTTPError as e:
            return {"ok": False, "error": type(e).__name__}


def _fid_from_token(token: str) -> str:
    # dev tokens are "dev-token-<persona>" -> "fl-<persona>"; production tokens map via GIGSIM_FREELANCER_ID
    if token.startswith("tok-"):
        return token[4:]
    return "fl-" + token.removeprefix("dev-token-")
