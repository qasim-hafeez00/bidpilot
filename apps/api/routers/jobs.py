from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from apps.api.auth.security import CurrentUser
from apps.api.queue import enqueue
from apps.api.schemas import JobDetail, JobRow, RunRef
from common import db
from common.tracing import trace_url

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _row(r: dict) -> JobRow:
    return JobRow(job_id=r["job_id"], title=r["title"], status=r["status"], fit=r["fit"], risk=r["risk"], decision=r["decision"],
                  price=r["price"], connects_cost=r["connects_cost"], risk_flags=r["risk_flags"], category=r["category"],
                  dup_of=r["dup_of"], updated_at=r["updated_at"].isoformat() if r["updated_at"] else None)


@router.get("", response_model=list[JobRow])
async def inbox(status: str | None = None, min_fit: float = 0.0, q: str | None = None, include_duplicates: bool = False,
                limit: int = Query(100, le=500), user=CurrentUser):
    sql = "SELECT * FROM jobs WHERE user_id=%s"
    args: list = [user["id"]]
    if status:
        sql += " AND status=%s"
        args.append(status)
    if not include_duplicates:
        sql += " AND status<>'duplicate'"
    if min_fit:
        sql += " AND COALESCE(fit,0)>=%s"
        args.append(min_fit)
    if q:
        sql += " AND title ILIKE %s"
        args.append(f"%{q}%")
    sql += " ORDER BY (status='awaiting_approval') DESC, COALESCE(fit,0) DESC, updated_at DESC LIMIT %s"
    args.append(limit)
    return [_row(r) for r in await db.fetch(sql, *args)]


@router.get("/{job_id}", response_model=JobDetail)
async def detail(job_id: str, user=CurrentUser):
    row = await db.fetchone("SELECT * FROM jobs WHERE user_id=%s AND job_id=%s", user["id"], job_id)
    if not row:
        raise HTTPException(404, "job not found")
    from agent import runtime

    g = await runtime.graph("bid")
    st = (await g.aget_state({"configurable": {"thread_id": row["thread_id"] or f"bid:{user['id']}:{job_id}"}})).values or {}
    runs = await db.fetch("SELECT run_id::text, status, started_at, latency_s, tokens_in, tokens_out, usd, trace_id FROM runs "
                          "WHERE user_id=%s AND job_id=%s ORDER BY started_at DESC LIMIT 20", user["id"], job_id)
    return JobDetail(job_id=job_id, status=row["status"], job=st.get("job") or row["data"] or {"title": row["title"]},
                     job_spec=st.get("job_spec"), risk_report=st.get("risk_report"), fit_report=st.get("fit_report"),
                     evidence=st.get("evidence", []), decision=st.get("decision"), price_quote=st.get("price_quote"),
                     attention_reason=st.get("attention_reason"), trace_id=row["trace_id"],
                     trace_url=trace_url(row["trace_id"]) if row["trace_id"] else None,
                     runs=[{**r, "started_at": r["started_at"].isoformat()} for r in runs])


@router.post("/{job_id}/analyze", response_model=RunRef)
async def analyze(job_id: str, force_bid: bool = False, user=CurrentUser):
    await db.execute("INSERT INTO jobs (user_id, job_id, status) VALUES (%s,%s,'queued') ON CONFLICT (user_id, job_id) DO UPDATE SET "
                     "status='queued', updated_at=now()", user["id"], job_id)
    rid = await enqueue("analyze_job", user["id"], job_id, force_bid, run_kind="bid", user_id=user["id"],
                        thread_id=f"bid:{user['id']}:{job_id}", job=job_id)
    return RunRef(run_id=rid)


@router.post("/{job_id}/skip")
async def skip(job_id: str, user=CurrentUser):
    await db.execute("UPDATE jobs SET status='skipped_by_user', updated_at=now() WHERE user_id=%s AND job_id=%s", user["id"], job_id)
    return {"ok": True}


@router.post("/scout", response_model=RunRef)
async def scout_now(user=CurrentUser):
    from apps.api.queue import pool

    p = await pool()
    await p.enqueue_job("scout_user", user["id"], _job_id=f"scout-manual:{user['id']}")
    return RunRef(run_id="scout", status="queued")
