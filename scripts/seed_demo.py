"""Create the reviewer account (persona ai_ml, GigSim connected, saved searches) and queue a first scout.

    REVIEWER_EMAIL / REVIEWER_PASSWORD env vars override the defaults (share them privately, never in the repo).
"""
from __future__ import annotations

import asyncio
import json
import os

from apps.api.auth.security import hash_pw, store_credential
from common import db


async def main() -> None:
    await db.init_schema()
    email = os.environ.get("REVIEWER_EMAIL", "reviewer@bidpilot.dev")
    pw = os.environ.get("REVIEWER_PASSWORD", "reviewer-pass-2026")
    u = await db.fetchone("SELECT id::text AS id FROM users WHERE email=%s", email)
    if not u:
        u = await db.fetchone("INSERT INTO users (email, password_hash, display_name, persona, role) VALUES (%s,%s,'Reviewer','ai_ml','reviewer') "
                              "RETURNING id::text AS id", email, hash_pw(pw))
        await db.execute("INSERT INTO user_settings (user_id) VALUES (%s)", u["id"])
    searches = [{"query": q, "skills": [], "limit": 20} for q in ("llm chatbot rag", "machine learning python", "computer vision")]
    await db.execute("UPDATE user_settings SET hourly_floor=34, min_fixed=300, weekly_connects_budget=80, saved_searches=%s, "
                     "onboarding_done=TRUE WHERE user_id=%s", json.dumps(searches), u["id"])
    await store_credential(u["id"], "gigsim", os.environ.get("REVIEWER_GIGSIM_TOKEN", "dev-token-ai_ml"))
    try:
        from apps.api.queue import pool

        await (await pool()).enqueue_job("scout_user", u["id"], _job_id=f"seed-scout:{u['id']}")
        print("queued first scout")
    except Exception as e:  # redis not running
        print("scout not queued:", type(e).__name__)
    print("reviewer ready:", email)


if __name__ == "__main__":
    asyncio.run(main())
