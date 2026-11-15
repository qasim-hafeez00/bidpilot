"""Proposal studio + approvals. Approving resumes the interrupted graph thread (Command(resume=...)) in the worker;
the pending approval is read from the checkpoint, so a page refresh never loses it."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api.auth.security import CurrentUser
from apps.api.queue import enqueue, pool
from apps.api.schemas import ApprovalIn, ProposalOut, RegenerateIn, RunRef
from common import db

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


async def _state(user_id: str, job_id: str):
    from agent import runtime

    row = await db.fetchone("SELECT thread_id, status FROM jobs WHERE user_id=%s AND job_id=%s", user_id, job_id)
    if not row:
        raise HTTPException(404, "job not found")
    g = await runtime.graph("bid")
    return row, await g.aget_state({"configurable": {"thread_id": row["thread_id"] or f"bid:{user_id}:{job_id}"}})


@router.get("/pending")
async def pending(user=CurrentUser):
    return await db.fetch("SELECT job_id, title, fit, price, connects_cost, updated_at FROM jobs WHERE user_id=%s AND status='awaiting_approval' "
                          "ORDER BY updated_at DESC", user["id"])


@router.get("/{job_id}", response_model=ProposalOut)
async def get(job_id: str, user=CurrentUser):
    row, snap = await _state(user["id"], job_id)
    st = snap.values or {}
    pend = None
    for t in snap.tasks or []:
        if t.interrupts:
            pend = t.interrupts[0].value
    return ProposalOut(job_id=job_id, status=row["status"], pending=pend, drafts=st.get("drafts", []), critiques=st.get("critiques", []),
                       verification=st.get("verification"), compliance=st.get("compliance_verdict"), submission=st.get("submission"),
                       attention_reason=st.get("attention_reason"))


@router.post("/{job_id}/decision", response_model=RunRef)
async def decide(job_id: str, body: ApprovalIn, user=CurrentUser):
    row, snap = await _state(user["id"], job_id)
    if not any(t.interrupts for t in (snap.tasks or [])):
        raise HTTPException(409, "nothing is waiting for approval on this job")
    if body.action == "reject" and not body.reason:
        raise HTTPException(422, "a reason is required to reject")
    await db.execute("UPDATE jobs SET status=%s, updated_at=now() WHERE user_id=%s AND job_id=%s",
                     "submitting" if body.action != "reject" else "rejecting", user["id"], job_id)
    rid = await enqueue("resume_bid", user["id"], job_id, {**body.model_dump(), "approver": user["email"]}, run_kind="bid",
                        user_id=user["id"], thread_id=row["thread_id"], job=job_id, job_id=f"resume:{user['id']}:{job_id}:{body.action}")
    return RunRef(run_id=rid)


@router.post("/{job_id}/regenerate")
async def regenerate(job_id: str, body: RegenerateIn, user=CurrentUser):
    """Regenerate one paragraph (runs in the worker; the new text is verified before it is returned)."""
    p = await pool()
    job = await p.enqueue_job("regenerate_paragraph", user["id"], job_id, body.paragraph, body.instruction or "")
    try:
        return await job.result(timeout=420)
    except TimeoutError as e:
        raise HTTPException(504, "regeneration is taking too long; try again") from e
