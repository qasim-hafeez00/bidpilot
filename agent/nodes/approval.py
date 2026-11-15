"""Human-in-the-loop (R4 / C5): dry-run preview -> interrupt() -> approve | edit | reject -> exactly-once submit.

* `prepare_approval` calls the write tools with dry_run=true so the approval screen shows exactly what would be sent and
  what it costs (Connects + balance). It runs BEFORE the interrupt so it is not re-executed on resume.
* `approval` interrupts with the full payload: draft, evidence behind every claim, risk report, price rationale, dry-run.
  Edits are diffed and fed to style memory (promotion rules), then re-checked by Compliance.
* `submit` uses idempotency keys derived from the thread id, so a crash/restart and re-run never submits twice.
"""
from __future__ import annotations

import difflib
import hashlib
from typing import Any

from langgraph.types import interrupt

from agent.handoffs import Approval
from agent.memory.store import record_edit
from agent.nodes import compliance
from agent.nodes._util import rec, toolbox, trace_id
from rag.verify import strip_markers


def _key(state: dict[str, Any], what: str, version: Any = "") -> str:
    base = f"{state.get('user_id')}:{state['job_id']}:{what}:{version}"
    return "bp-" + hashlib.sha256(base.encode()).hexdigest()[:32]


async def prepare(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    draft, price = state["drafts"][-1], state["price_quote"]
    tb, tid = toolbox(config), trace_id(state, config)
    preview = await tb.call("approval", "create_proposal_draft", {
        "job_id": state["job_id"], "cover_letter": strip_markers(draft["cover_letter"]),
        "screening_answers": [strip_markers(a) for a in draft.get("screening_answers", [])],
        "bid_amount": price["amount"], "bid_type": price["bid_type"],
        "idempotency_key": _key(state, "draft", draft["version"]), "dry_run": True}, tid)
    bal = await tb.call("approval", "get_connects_balance", {}, tid)
    dry = {"payload": preview.get("preview"), "connects_cost": preview.get("connects_cost"), "balance": bal.get("balance"),
           "balance_after": (bal.get("balance") or 0) - (preview.get("connects_cost") or 0), "marketplace": preview.get("marketplace")}
    return {"dry_run": dry, "status": "awaiting_approval", "steps": 1,
            "trace": [rec("prepare_approval", tool="create_proposal_draft(dry_run)", connects=dry["connects_cost"])]}


def payload(state: dict[str, Any]) -> dict[str, Any]:
    draft = state["drafts"][-1]
    ev = {e["evidence_id"]: e for e in state.get("evidence", [])}
    claims = state.get("verification", {}).get("claims", [])
    return {
        "kind": "proposal", "job_id": state["job_id"], "title": state["job"].get("title"),
        "draft": {"cover_letter": draft["cover_letter"], "screening_answers": draft.get("screening_answers", []),
                  "version": draft["version"], "mode": draft.get("mode")},
        "claims": [{**c, "evidence": ev.get(c.get("evidence_id"), {}).get("snippet", "")[:300]} for c in claims],
        "evidence": list(ev.values()), "risk_report": state.get("risk_report"), "fit_report": state.get("fit_report"),
        "price_quote": state.get("price_quote"), "dry_run": state.get("dry_run"),
        "critique": (state.get("critiques") or [{}])[-1], "compliance": state.get("compliance_verdict"),
        "verification": {k: state.get("verification", {}).get(k) for k in ("before", "after", "removed")},
        "notes": state.get("attention_reason"),
    }


async def approval(state: dict[str, Any], config: dict[str, Any], *, store=None) -> dict[str, Any]:
    raw = interrupt(payload(state))
    a = Approval(**raw)
    out: dict[str, Any] = {"approvals": [a.model_dump()], "steps": 1}
    if a.action == "reject":
        out.update(status="rejected", attention_reason=a.reason or "rejected by user",
                   trace=[rec("approval", action="reject", reason=a.reason)])
        return out
    if a.action == "edit" and a.edited_text:
        draft = dict(state["drafts"][-1])
        original = strip_markers(draft["cover_letter"])
        diff = list(difflib.unified_diff(original.split(". "), a.edited_text.split(". "), lineterm="", n=0))[:40]
        mem = await record_edit(store, state.get("user_id", "anon"), original, a.edited_text) if store else {}
        verdict = compliance.evaluate(a.edited_text, a.edited_answers or draft.get("screening_answers", []),
                                      bool(state.get("risk_report", {}).get("injection_detected")))
        draft.update(cover_letter=verdict.fixed_text or a.edited_text, version=draft["version"] + 1, mode="human_edit",
                     screening_answers=a.edited_answers or draft.get("screening_answers", []), diff=diff)
        out["drafts"] = [draft]
        out["compliance_verdict"] = verdict.model_dump()
        out["trace"] = [rec("approval", action="edit", diff_lines=len(diff), memory=mem, compliance=verdict.status)]
        if verdict.status == "block":
            out.update(status="awaiting_approval", attention_reason=f"Your edit was blocked by Compliance: {verdict.reason}")
            return out
        out["status"] = "approved"
        return out
    out.update(status="approved", trace=[rec("approval", action="approve", approver=a.approver)])
    return out


async def submit(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Exactly once: idempotency keys are a pure function of (user, job, draft version)."""
    draft, price = state["drafts"][-1], state["price_quote"]
    tb, tid = toolbox(config), trace_id(state, config)
    d = await tb.call("submitter", "create_proposal_draft", {
        "job_id": state["job_id"], "cover_letter": strip_markers(draft["cover_letter"]),
        "screening_answers": [strip_markers(x) for x in draft.get("screening_answers", [])],
        "bid_amount": price["amount"], "bid_type": price["bid_type"],
        "idempotency_key": _key(state, "draft", draft["version"])}, tid)
    s = await tb.call("submitter", "submit_proposal", {"proposal_id": d["proposal_id"],
                                                       "idempotency_key": _key(state, "submit")}, tid)
    status = "submitted" if s.get("status") == "submitted" else "draft_on_marketplace"
    return {"submission": {"proposal_id": d["proposal_id"], **s, "draft_replay": d.get("idempotent_replay")}, "status": status,
            "steps": 1, "trace": [rec("submit", tool="submit_proposal", proposal_id=d["proposal_id"], status=s.get("status"),
                                      replay=s.get("idempotent_replay"), connects=s.get("connects_spent"))]}
