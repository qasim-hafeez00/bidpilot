"""OAuth 2.1 (authorization code + PKCE) for the official Upwork MCP server (A4).

Discovery: RFC 9728 protected-resource metadata on the MCP server -> authorization server -> RFC 8414 metadata.
Client: UPWORK_CLIENT_ID (+ optional secret) from env, or RFC 7591 dynamic registration when the server allows it.
Tokens are stored encrypted per user (apps/api/auth/security.store_credential) and never logged.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from apps.api.auth.security import CurrentUser, store_credential
from mcp_servers.marketplace.adapters.upwork_live import UPWORK_MCP_URL

router = APIRouter(prefix="/api/auth/upwork", tags=["auth"])
_pending: dict[str, dict] = {}  # state -> {verifier, user_id, ts}; short-lived


async def _metadata() -> dict:
    base = UPWORK_MCP_URL.split("/mcp")[0]
    async with httpx.AsyncClient(timeout=10) as c:
        prm = await c.get(f"{base}/.well-known/oauth-protected-resource")
        auth_server = prm.json()["authorization_servers"][0] if prm.status_code == 200 else base
        meta = await c.get(f"{auth_server.rstrip('/')}/.well-known/oauth-authorization-server")
        if meta.status_code != 200:
            raise HTTPException(502, "Upwork authorization server metadata unavailable")
        return meta.json()


async def _client_id(meta: dict, redirect_uri: str) -> tuple[str, str | None]:
    if os.environ.get("UPWORK_CLIENT_ID"):
        return os.environ["UPWORK_CLIENT_ID"], os.environ.get("UPWORK_CLIENT_SECRET")
    if not meta.get("registration_endpoint"):
        raise HTTPException(400, "Set UPWORK_CLIENT_ID: the authorization server does not allow dynamic registration")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(meta["registration_endpoint"], json={"client_name": "BidPilot", "redirect_uris": [redirect_uri],
                                                               "grant_types": ["authorization_code", "refresh_token"],
                                                               "token_endpoint_auth_method": "none"})
    if r.status_code >= 300:
        raise HTTPException(502, "dynamic client registration failed")
    return r.json()["client_id"], None


@router.get("/start")
async def start(request: Request, user=CurrentUser):
    meta = await _metadata()
    redirect_uri = str(request.url_for("upwork_callback"))
    cid, _ = await _client_id(meta, redirect_uri)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    _pending[state] = {"verifier": verifier, "user_id": user["id"], "ts": time.time(), "client_id": cid, "redirect_uri": redirect_uri}
    q = urlencode({"response_type": "code", "client_id": cid, "redirect_uri": redirect_uri, "state": state,
                   "code_challenge": challenge, "code_challenge_method": "S256", "resource": UPWORK_MCP_URL})
    return {"authorize_url": f"{meta['authorization_endpoint']}?{q}"}


@router.get("/callback", name="upwork_callback")
async def callback(code: str, state: str):
    p = _pending.pop(state, None)
    if not p or time.time() - p["ts"] > 600:
        raise HTTPException(400, "invalid or expired OAuth state")
    meta = await _metadata()
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": p["redirect_uri"], "client_id": p["client_id"],
            "code_verifier": p["verifier"], "resource": UPWORK_MCP_URL}
    if os.environ.get("UPWORK_CLIENT_SECRET"):
        data["client_secret"] = os.environ["UPWORK_CLIENT_SECRET"]
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(meta["token_endpoint"], data=data)
    if r.status_code >= 300:
        raise HTTPException(502, "token exchange failed")
    t = r.json()
    await store_credential(p["user_id"], "upwork", t["access_token"], t.get("refresh_token"),
                           time.time() + float(t.get("expires_in", 3600)), t.get("scope"))
    return RedirectResponse("/settings?upwork=connected")
