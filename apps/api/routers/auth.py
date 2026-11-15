from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from apps.api.auth.security import COOKIE, CurrentUser, check_pw, hash_pw, session_token, store_credential
from apps.api.schemas import AuthOut, LoginIn, OnboardingIn, RegisterIn, Settings, UserOut
from common import db
from common.config import ROOT

router = APIRouter(prefix="/api", tags=["auth"])
PERSONA_ROOT = ROOT / "data" / "personas"


async def _user_out(uid: str) -> UserOut:
    u = await db.fetchone("SELECT u.id::text AS id, u.email, u.display_name, u.persona, u.role, s.* FROM users u "
                          "LEFT JOIN user_settings s ON s.user_id=u.id WHERE u.id=%s", uid)
    st = None
    if u.get("hourly_floor") is not None:
        st = Settings(hourly_floor=float(u["hourly_floor"]), min_fixed=float(u["min_fixed"]), weekly_connects_budget=u["weekly_connects_budget"],
                      autonomy=u["autonomy"], saved_searches=u["saved_searches"] or [], marketplace_mode=u["marketplace_mode"])
    return UserOut(id=u["id"], email=u["email"], display_name=u["display_name"], persona=u["persona"], role=u["role"],
                   onboarding_done=bool(u.get("onboarding_done")), settings=st)


def _set_cookie(resp: Response, tok: str) -> None:
    resp.set_cookie(COOKIE, tok, httponly=True, samesite="lax", secure=False, max_age=7 * 86400)


@router.post("/auth/register", response_model=AuthOut)
async def register(body: RegisterIn, resp: Response):
    if await db.fetchone("SELECT 1 AS x FROM users WHERE email=%s", body.email.lower()):
        raise HTTPException(409, "email already registered")
    row = await db.fetchone("INSERT INTO users (email, password_hash, display_name) VALUES (%s,%s,%s) RETURNING id::text AS id",
                            body.email.lower(), hash_pw(body.password), body.display_name)
    await db.execute("INSERT INTO user_settings (user_id) VALUES (%s)", row["id"])
    tok = session_token(row["id"])
    _set_cookie(resp, tok)
    return AuthOut(token=tok, user=await _user_out(row["id"]))


@router.post("/auth/login", response_model=AuthOut)
async def login(body: LoginIn, resp: Response):
    u = await db.fetchone("SELECT id::text AS id, password_hash FROM users WHERE email=%s", body.email.lower())
    if not u or not check_pw(body.password, u["password_hash"]):
        raise HTTPException(401, "wrong email or password")
    tok = session_token(u["id"])
    _set_cookie(resp, tok)
    return AuthOut(token=tok, user=await _user_out(u["id"]))


@router.post("/auth/logout")
async def logout(resp: Response):
    resp.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user=CurrentUser):
    return await _user_out(user["id"])


@router.post("/onboarding", response_model=UserOut)
async def onboarding(body: OnboardingIn, user=CurrentUser):
    persona = body.persona if body.persona != "own" else f"user-{user['id'][:8]}"
    if body.persona == "own":
        (PERSONA_ROOT / persona / "uploads").mkdir(parents=True, exist_ok=True)
    await db.execute("UPDATE users SET persona=%s WHERE id=%s", persona, user["id"])
    await db.execute("UPDATE user_settings SET hourly_floor=%s, min_fixed=%s, weekly_connects_budget=%s, autonomy=%s, saved_searches=%s, "
                     "marketplace_mode=%s, onboarding_done=TRUE WHERE user_id=%s", body.hourly_floor, body.min_fixed,
                     body.weekly_connects_budget, body.autonomy, json.dumps([s.model_dump() for s in body.saved_searches]),
                     body.marketplace_mode, user["id"])
    token = body.gigsim_token or (f"dev-token-{body.persona}" if body.persona != "own" else "dev-token-reviewer")
    await store_credential(user["id"], "gigsim", token)
    return await _user_out(user["id"])


@router.post("/portfolio/upload")
async def upload(files: list[UploadFile] = File(...), user=CurrentUser):
    """Add work (Markdown/text case studies, PDF CV). Indexed incrementally: only new chunks are embedded."""
    dest = PERSONA_ROOT / user["persona"] / "uploads"
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files[:10]:
        name = Path(f.filename or "upload.md").name
        if Path(name).suffix.lower() not in (".md", ".txt", ".pdf"):
            raise HTTPException(400, f"unsupported file type: {name}")
        with open(dest / name, "wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(name)
    from agent import runtime

    for key in [k for k in list(runtime._toolboxes) if k.startswith(user["id"])]:  # restart portfolio session -> re-index
        tb = runtime._toolboxes.pop(key)
        await tb.close()
    return {"saved": saved, "persona": user["persona"], "reindex": "incremental (embedding cache)"}
