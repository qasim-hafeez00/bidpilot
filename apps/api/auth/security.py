"""Users, sessions (JWT in an httpOnly cookie or Bearer header) and the encrypted credential store."""
from __future__ import annotations

import os
import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request

from common import db
from common.secrets import encrypt

COOKIE = "bp_session"


def _secret() -> str:
    return os.environ.get("APP_SECRET_KEY", "dev-only-secret-change-me")


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=11)).decode()


def check_pw(pw: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), h.encode())
    except ValueError:
        return False


def session_token(user_id: str) -> str:
    return jwt.encode({"sub": user_id, "exp": int(time.time()) + 7 * 86400}, _secret(), algorithm="HS256")


async def current_user(request: Request) -> dict:
    tok = request.cookies.get(COOKIE) or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not tok:
        raise HTTPException(401, "not signed in")
    try:
        uid = jwt.decode(tok, _secret(), algorithms=["HS256"])["sub"]
    except jwt.PyJWTError as e:
        raise HTTPException(401, "session expired") from e
    u = await db.fetchone("SELECT u.id::text AS id, u.email, u.display_name, u.persona, u.role, s.onboarding_done FROM users u "
                          "LEFT JOIN user_settings s ON s.user_id=u.id WHERE u.id=%s", uid)
    if not u:
        raise HTTPException(401, "unknown user")
    return u


CurrentUser = Depends(current_user)


async def store_credential(user_id: str, provider: str, access: str, refresh: str | None = None,
                           expires_at: float | None = None, scope: str | None = None) -> None:
    """Tokens are encrypted at rest (Fernet) and never logged."""
    await db.execute("INSERT INTO credentials (user_id, provider, enc_access, enc_refresh, expires_at, scope) VALUES "
                     "(%s,%s,%s,%s,to_timestamp(%s),%s) ON CONFLICT (user_id, provider) DO UPDATE SET enc_access=EXCLUDED.enc_access, "
                     "enc_refresh=EXCLUDED.enc_refresh, expires_at=EXCLUDED.expires_at, scope=EXCLUDED.scope, updated_at=now()",
                     user_id, provider, encrypt(access), encrypt(refresh) if refresh else None, expires_at, scope)
