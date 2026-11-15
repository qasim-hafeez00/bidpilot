"""Encryption for OAuth / marketplace tokens at rest (Fernet) and short-lived per-user MCP bearer JWTs."""
from __future__ import annotations

import base64
import hashlib
import os
import time
from typing import Any

import jwt
from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    raw = os.environ.get("TOKEN_ENC_KEY") or os.environ.get("APP_SECRET_KEY", "dev-only-secret-change-me")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def _jwt_secret() -> str:
    return os.environ.get("MCP_JWT_SECRET", "dev-mcp-jwt-secret-change-me")


def mint_user_token(user_id: str, persona: str, gigsim_token: str | None = None, upwork_token: str | None = None,
                    ttl_s: int = 3600) -> str:
    claims: dict[str, Any] = {"sub": user_id, "persona": persona, "iat": int(time.time()), "exp": int(time.time()) + ttl_s}
    if gigsim_token:
        claims["gst"] = encrypt(gigsim_token)
    if upwork_token:
        claims["ut"] = encrypt(upwork_token)
    return jwt.encode(claims, _jwt_secret(), algorithm="HS256")


def verify_user_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
