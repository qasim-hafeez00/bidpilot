from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api.auth.security import CurrentUser
from apps.api.queue import enqueue
from apps.api.schemas import ApprovalIn, ConversationRow, RunRef, ThreadOut
from common import db

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("", response_model=list[ConversationRow])
async def threads(user=CurrentUser):
    rows = await db.fetch("SELECT * FROM conversations WHERE user_id=%s ORDER BY last_message_at DESC NULLS LAST", user["id"])
    return [ConversationRow(thread_id=r["thread_id"], title=r["title"], status=r["status"], intent=r["intent"], proposal_id=r["proposal_id"],
                            last_message_at=r["last_message_at"].isoformat() if r["last_message_at"] else None) for r in rows]


@router.get("/{thread_id}", response_model=ThreadOut)
async def thread(thread_id: str, user=CurrentUser):
    from agent import runtime

    conv = await db.fetchone("SELECT * FROM conversations WHERE user_id=%s AND thread_id=%s", user["id"], thread_id)
    if not conv:
        raise HTTPException(404, "thread not found")
    u = await runtime.user_ctx(user["id"])
    tb = await runtime.toolbox(u)
    try:
        msgs = (await tb.call("pipeline", "list_messages", {"thread_id": thread_id})).get("messages", [])
    except Exception as e:
        raise HTTPException(503, f"marketplace unavailable: {type(e).__name__}") from e
    pend = None
    if conv.get("graph_thread"):
        g = await runtime.graph("conversation")
        snap = await g.aget_state({"configurable": {"thread_id": conv["graph_thread"]}})
        for t in snap.tasks or []:
            if t.interrupts:
                pend = t.interrupts[0].value
    return ThreadOut(thread_id=thread_id, messages=msgs, pending=pend, status=conv["status"])


@router.post("/{thread_id}/draft", response_model=RunRef)
async def draft(thread_id: str, user=CurrentUser):
    rid = await enqueue("conversation", user["id"], thread_id, None, run_kind="conversation", user_id=user["id"], thread_id=thread_id,
                        job_id=f"conv-manual:{user['id']}:{thread_id}")
    return RunRef(run_id=rid)


@router.post("/{thread_id}/decision", response_model=RunRef)
async def decide(thread_id: str, body: ApprovalIn, user=CurrentUser):
    if body.action == "reject" and not body.reason:
        raise HTTPException(422, "a reason is required to reject")
    rid = await enqueue("conversation", user["id"], thread_id, {**body.model_dump(), "approver": user["email"]}, run_kind="conversation",
                        user_id=user["id"], thread_id=thread_id, job_id=f"conv-resume:{user['id']}:{thread_id}:{body.action}")
    await db.execute("INSERT INTO approvals_log (user_id, thread_id, kind, action, reason) VALUES (%s,%s,'message',%s,%s)",
                     user["id"], thread_id, body.action, body.reason)
    return RunRef(run_id=rid)
