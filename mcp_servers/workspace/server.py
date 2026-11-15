"""Workspace MCP server: free calendar slots, tentative interview holds, email drafts.

Backed by a documented LOCAL MOCK (SQLite) - no Google account is required; swapping in Google Calendar/Gmail only
changes the three functions marked BACKEND. Agents see MCP tools only. Nothing is ever sent: holds are tentative
and emails are drafts.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_servers.common import ROOT, AuditLog, current_identity, run

audit = AuditLog("workspace")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_lock = threading.Lock()


def _db() -> sqlite3.Connection:
    p = Path(os.environ.get("WORKSPACE_DB", ROOT / "data" / "processed" / "workspace.db"))
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(p), check_same_thread=False)
    db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, user TEXT, start TEXT, end TEXT, title TEXT, kind TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, user TEXT, body TEXT, created TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS idem (k TEXT PRIMARY KEY, v TEXT)")
    return db


class Slot(BaseModel):
    start: str
    end: str
    label: str


class SlotsResult(BaseModel):
    timezone: str
    slots: list[Slot]


class HoldResult(BaseModel):
    hold_id: str
    start: str
    end: str
    status: str
    idempotent_replay: bool = False


class EmailDraftResult(BaseModel):
    draft_id: str
    status: str
    idempotent_replay: bool = False


mcp = FastMCP("bidpilot-workspace", instructions="Calendar availability, tentative interview holds and email drafts. "
              "Nothing here sends anything: holds are tentative and emails are drafts.")


def _busy(user: str) -> list[tuple[dt.datetime, dt.datetime]]:  # BACKEND
    rows = _db().execute("SELECT start, end FROM events WHERE user=?", (user,)).fetchall()
    return [(dt.datetime.fromisoformat(a), dt.datetime.fromisoformat(b)) for a, b in rows]


@mcp.tool(title="Find free interview slots", annotations=READ, structured_output=True)
def get_free_slots(start_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="First day, YYYY-MM-DD.")],
                   days: Annotated[int, Field(ge=1, le=14)] = 5,
                   duration_min: Annotated[int, Field(ge=15, le=120)] = 30,
                   timezone: Annotated[str, Field(max_length=64)] = "Asia/Karachi",
                   max_slots: Annotated[int, Field(ge=1, le=10)] = 3,
                   trace_id: str | None = None) -> SlotsResult:
    """Free slots inside working hours (10:00-18:00, Mon-Fri) that do not clash with existing events."""
    user = current_identity()["user_id"]
    tz = ZoneInfo(timezone)
    busy = _busy(user)
    out: list[Slot] = []
    day = dt.date.fromisoformat(start_date)
    for d in range(days * 2):
        cur = day + dt.timedelta(days=d)
        if cur.weekday() >= 5:
            continue
        for hour in (10, 11, 14, 15, 16):
            s = dt.datetime.combine(cur, dt.time(hour), tz)
            e = s + dt.timedelta(minutes=duration_min)
            if any(s < b_e and e > b_s for b_s, b_e in busy):
                continue
            out.append(Slot(start=s.isoformat(), end=e.isoformat(), label=s.strftime("%a %d %b, %H:%M") + f" ({timezone})"))
            break  # one per day keeps offers spread out
        if len(out) >= max_slots:
            break
    audit.write("get_free_slots", {"start_date": start_date, "days": days}, {"n": len(out)}, trace_id)
    return SlotsResult(timezone=timezone, slots=out)


@mcp.tool(title="Create tentative interview hold", annotations=WRITE, structured_output=True)
def create_interview_hold(start: Annotated[str, Field(description="ISO-8601 start with offset.")],
                          duration_min: Annotated[int, Field(ge=15, le=120)],
                          title: Annotated[str, Field(min_length=3, max_length=120)],
                          idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
                          trace_id: str | None = None) -> HoldResult:
    """Place a TENTATIVE hold on the calendar (no invite is sent)."""
    user = current_identity()["user_id"]
    with _lock:
        db = _db()
        if r := db.execute("SELECT v FROM idem WHERE k=?", (f"{user}:{idempotency_key}",)).fetchone():
            return HoldResult(**{**json.loads(r[0]), "idempotent_replay": True})
        s = dt.datetime.fromisoformat(start)
        e = s + dt.timedelta(minutes=duration_min)
        hid = "hold-" + uuid.uuid4().hex[:8]
        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (hid, user, s.isoformat(), e.isoformat(), title, "tentative"))  # BACKEND
        res = HoldResult(hold_id=hid, start=s.isoformat(), end=e.isoformat(), status="tentative")
        db.execute("INSERT INTO idem VALUES (?,?)", (f"{user}:{idempotency_key}", res.model_dump_json()))
        db.commit()
    audit.write("create_interview_hold", {"start": start, "title": title}, res.model_dump(), trace_id)
    return res


@mcp.tool(title="Create email draft", annotations=WRITE, structured_output=True)
def create_email_draft(to_label: Annotated[str, Field(min_length=2, max_length=120, description="Recipient label, not an address.")],
                       subject: Annotated[str, Field(min_length=2, max_length=200)],
                       body: Annotated[str, Field(min_length=2, max_length=5000)],
                       idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
                       trace_id: str | None = None) -> EmailDraftResult:
    """Save an email DRAFT for the user to review (never sent)."""
    user = current_identity()["user_id"]
    with _lock:
        db = _db()
        if r := db.execute("SELECT v FROM idem WHERE k=?", (f"{user}:{idempotency_key}",)).fetchone():
            return EmailDraftResult(**{**json.loads(r[0]), "idempotent_replay": True})
        did = "draft-" + uuid.uuid4().hex[:8]
        db.execute("INSERT INTO drafts VALUES (?,?,?,?)", (did, user, json.dumps({"to": to_label, "subject": subject, "body": body}),
                                                           dt.datetime.now(dt.UTC).isoformat()))  # BACKEND
        res = EmailDraftResult(draft_id=did, status="draft")
        db.execute("INSERT INTO idem VALUES (?,?)", (f"{user}:{idempotency_key}", res.model_dump_json()))
        db.commit()
    audit.write("create_email_draft", {"to": to_label, "subject": subject}, res.model_dump(), trace_id)
    return res


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "workspace-mcp", "backend": "local-mock-sqlite"})


def main() -> None:
    run(mcp, default_port=8103)


if __name__ == "__main__":
    main()
