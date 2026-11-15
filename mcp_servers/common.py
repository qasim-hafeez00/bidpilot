"""Shared MCP-server plumbing: identity (bearer JWT over HTTP, env over stdio), rate limiting, audit log, runner."""
from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from common.pii import mask_obj
from common.secrets import decrypt, verify_user_token

ROOT = Path(__file__).resolve().parents[1]
identity: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("identity", default=None)


def current_identity() -> dict[str, Any]:
    ident = identity.get()
    if ident:
        return ident
    # stdio / single-user mode: identity from the environment of the spawned server
    tok = os.environ.get("MCP_USER_JWT")
    if tok:
        return _claims_to_identity(verify_user_token(tok))
    return {"user_id": os.environ.get("MCP_USER_ID", "local-dev"), "persona": os.environ.get("PORTFOLIO_PERSONA", "ai_ml"),
            "gigsim_token": os.environ.get("GIGSIM_TOKEN", "dev-token-ai_ml"), "upwork_token": os.environ.get("UPWORK_ACCESS_TOKEN")}


def _claims_to_identity(c: dict[str, Any]) -> dict[str, Any]:
    return {"user_id": c["sub"], "persona": c.get("persona", "ai_ml"),
            "gigsim_token": decrypt(c["gst"]) if c.get("gst") else None,
            "upwork_token": decrypt(c["ut"]) if c.get("ut") else None}


class BearerAuthMiddleware:
    """ASGI middleware for the Streamable-HTTP endpoint: requires `Authorization: Bearer <per-user JWT>`."""

    def __init__(self, app, open_paths: tuple[str, ...] = ("/health",), admin_paths: tuple[str, ...] = ("/admin",)):
        self.app, self.open_paths, self.admin_paths = app, open_paths, admin_paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or any(scope["path"].startswith(p) for p in self.open_paths):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        tok = headers.get("authorization", "").removeprefix("Bearer ").strip()
        if any(scope["path"].startswith(p) for p in self.admin_paths):
            if tok and tok == os.environ.get("MCP_ADMIN_TOKEN", "dev-mcp-admin"):
                return await self.app(scope, receive, send)
            return await _deny(send, "admin token required")
        try:
            ident = _claims_to_identity(verify_user_token(tok))
        except Exception:
            return await _deny(send, "invalid or missing bearer token")
        token = identity.set(ident)
        try:
            return await self.app(scope, receive, send)
        finally:
            identity.reset(token)


async def _deny(send, msg: str) -> None:
    body = json.dumps({"error": msg}).encode()
    await send({"type": "http.response.start", "status": 401,
                "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
    await send({"type": "http.response.body", "body": body})


class RateLimiter:
    """Per-user sliding window that WAITS (polite) instead of hammering the upstream; fails only if the wait is long."""

    def __init__(self, per_minute: int, max_wait_s: float = 15.0):
        self.per_minute, self.max_wait_s = per_minute, max_wait_s
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def acquire(self, user: str) -> None:
        async with self.lock:
            dq = self.hits[user]
            now = time.monotonic()
            while dq and now - dq[0] > 60:
                dq.popleft()
            if len(dq) >= self.per_minute:
                wait = 60 - (now - dq[0]) + 0.05
                if wait > self.max_wait_s:
                    raise RuntimeError(f"rate_limited: local limiter ({self.per_minute}/min) - retry in {wait:.0f}s")
                await asyncio.sleep(wait)
            dq.append(time.monotonic())


class AuditLog:
    """Append-only JSONL audit log (user, tool, args, result, trace id). PII is masked before writing."""

    def __init__(self, name: str):
        self.path = Path(os.environ.get("AUDIT_DIR", ROOT / "data" / "processed" / "audit")) / f"{name}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, tool: str, args: dict[str, Any], result: Any, trace_id: str | None, ok: bool = True) -> None:
        ident = current_identity()
        rec = {"ts": time.time(), "user": ident.get("user_id"), "tool": tool, "trace_id": trace_id, "ok": ok,
               "args": mask_obj(args), "result": mask_obj(result if isinstance(result, dict | list | str) else str(result))}
        line = json.dumps(rec, default=str)
        with open(self.path, "a", encoding="utf-8") as fh:  # append-only
            fh.write(line + "\n")
        try:
            from common.db import audit_insert

            audit_insert(rec)
        except Exception:
            pass


def run(mcp, default_port: int) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", default=os.environ.get("MCP_TRANSPORT", "stdio"), choices=["stdio", "http"])
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", default_port)))
    a = ap.parse_args()
    if a.transport == "stdio":
        mcp.run("stdio")
        return
    import uvicorn

    app = BearerAuthMiddleware(mcp.streamable_http_app())
    uvicorn.run(app, host="0.0.0.0", port=a.port, log_level="warning")
