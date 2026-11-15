"""Postgres access (psycopg 3). Every query on user data is scoped by user_id (tenant). The audit table is append-only
(UPDATE/DELETE raise via trigger). LangGraph's checkpointer and store live in the same database, in their own tables."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  display_name TEXT, persona TEXT NOT NULL DEFAULT 'ai_ml', role TEXT NOT NULL DEFAULT 'user', created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS user_settings (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, hourly_floor NUMERIC NOT NULL DEFAULT 30,
  min_fixed NUMERIC NOT NULL DEFAULT 200, weekly_connects_budget INT NOT NULL DEFAULT 80, autonomy TEXT NOT NULL DEFAULT 'suggest',
  saved_searches JSONB NOT NULL DEFAULT '[]', marketplace_mode TEXT NOT NULL DEFAULT 'gigsim', onboarding_done BOOLEAN DEFAULT FALSE,
  variant_override TEXT);
CREATE TABLE IF NOT EXISTS credentials (
  user_id UUID REFERENCES users(id) ON DELETE CASCADE, provider TEXT NOT NULL, enc_access TEXT NOT NULL, enc_refresh TEXT,
  expires_at TIMESTAMPTZ, scope TEXT, updated_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (user_id, provider));
CREATE TABLE IF NOT EXISTS jobs (
  user_id UUID REFERENCES users(id) ON DELETE CASCADE, job_id TEXT NOT NULL, title TEXT, data JSONB, status TEXT NOT NULL DEFAULT 'new',
  fit REAL, risk REAL, decision TEXT, price JSONB, connects_cost INT, risk_flags JSONB, thread_id TEXT, trace_id TEXT, dup_of TEXT,
  category TEXT, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (user_id, job_id));
CREATE TABLE IF NOT EXISTS runs (
  run_id UUID PRIMARY KEY, user_id UUID REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL, thread_id TEXT NOT NULL,
  job_id TEXT, status TEXT NOT NULL DEFAULT 'queued', started_at TIMESTAMPTZ DEFAULT now(), finished_at TIMESTAMPTZ,
  latency_s REAL, tokens_in INT DEFAULT 0, tokens_out INT DEFAULT 0, usd REAL DEFAULT 0, trace_id TEXT, error TEXT, resume JSONB);
CREATE TABLE IF NOT EXISTS run_events (
  id BIGSERIAL PRIMARY KEY, run_id UUID REFERENCES runs(run_id) ON DELETE CASCADE, ts TIMESTAMPTZ DEFAULT now(), node TEXT, data JSONB);
CREATE INDEX IF NOT EXISTS run_events_run ON run_events(run_id, id);
CREATE TABLE IF NOT EXISTS pipeline (
  user_id UUID REFERENCES users(id) ON DELETE CASCADE, proposal_id TEXT NOT NULL, job_id TEXT, title TEXT, stage TEXT NOT NULL,
  thread_id TEXT, category TEXT, opening_style TEXT, connects_spent INT DEFAULT 0, bid JSONB, updated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, proposal_id));
CREATE TABLE IF NOT EXISTS conversations (
  user_id UUID REFERENCES users(id) ON DELETE CASCADE, thread_id TEXT NOT NULL, proposal_id TEXT, job_id TEXT, title TEXT,
  last_message_at TIMESTAMPTZ, status TEXT DEFAULT 'new', graph_thread TEXT, intent TEXT, PRIMARY KEY (user_id, thread_id));
CREATE TABLE IF NOT EXISTS approvals_log (
  id BIGSERIAL PRIMARY KEY, user_id UUID REFERENCES users(id) ON DELETE CASCADE, thread_id TEXT, kind TEXT, action TEXT,
  reason TEXT, diff JSONB, ts TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS seen_jobs (
  user_id UUID REFERENCES users(id) ON DELETE CASCADE, job_id TEXT NOT NULL, dup_of TEXT, seen_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, job_id));
CREATE TABLE IF NOT EXISTS cursors (user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, last_event_id INT DEFAULT 0,
  last_scout_at DOUBLE PRECISION DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY, ts DOUBLE PRECISION, user_id TEXT, tool TEXT, trace_id TEXT, ok BOOLEAN, args JSONB, result JSONB);
CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_no_change ON audit_log;
CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_append_only();
"""

_pool: AsyncConnectionPool | None = None


def dsn() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://bidpilot:bidpilot@localhost:15432/bidpilot")
    return url.replace("postgresql+psycopg://", "postgresql://")


async def pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(dsn(), min_size=1, max_size=int(os.environ.get("DB_POOL", "8")), open=False,
                                    kwargs={"autocommit": True, "row_factory": dict_row})
        await _pool.open()
    return _pool


async def init_schema() -> None:
    p = await pool()
    async with p.connection() as c:
        await c.execute(SCHEMA)


@asynccontextmanager
async def conn():
    p = await pool()
    async with p.connection() as c:
        yield c


async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
    async with conn() as c:
        cur = await c.execute(sql, args)
        return await cur.fetchall() if cur.description else []


async def fetchone(sql: str, *args: Any) -> dict[str, Any] | None:
    rows = await fetch(sql, *args)
    return rows[0] if rows else None


async def execute(sql: str, *args: Any) -> None:
    async with conn() as c:
        await c.execute(sql, args)


def J(obj: Any) -> str:
    return json.dumps(obj, default=str)


def audit_insert(rec: dict[str, Any]) -> None:
    """Synchronous insert used by MCP servers (separate processes) when DATABASE_URL is configured."""
    if not os.environ.get("AUDIT_TO_DB"):
        return
    with psycopg.connect(dsn(), autocommit=True) as c:
        c.execute("INSERT INTO audit_log (ts, user_id, tool, trace_id, ok, args, result) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                  (rec["ts"], rec["user"], rec["tool"], rec["trace_id"], rec["ok"], J(rec["args"]), J(rec["result"])))
