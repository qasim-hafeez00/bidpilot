"""Typed graph state (C2).

Three things are kept apart:
  * STATE (this TypedDict): what this job / conversation needs right now - checkpointed in Postgres.
  * EXECUTION TRACE: every tool name/argument/result -> `trace` (append-only reducer) + LangSmith/Phoenix + MCP audit log.
  * LONG-TERM MEMORY: promoted knowledge only, in the LangGraph store (agent/memory/store.py), never raw tool output.
Reducers are used wherever parallel branches (analyst / risk / fit) write.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_dict(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


SEVERITY = {"dead_letter": 9, "queued_degraded": 8, "needs_attention": 7, "blocked": 6, "rejected": 5}


def merge_status(a: str | None, b: str | None) -> str | None:
    """Parallel branches may all write `status`; keep the most severe halt, otherwise the newest value."""
    if a in SEVERITY and SEVERITY.get(a, 0) > SEVERITY.get(b or "", 0) and b not in ("running",):
        return a
    return b if b is not None else a


def last_nonempty(a: str | None, b: str | None) -> str | None:
    return b or a


class BidState(TypedDict, total=False):
    # identity
    user_id: str
    persona: str
    job_id: str
    trace_id: str
    # inputs
    job: dict[str, Any]
    settings: dict[str, Any]
    # parallel analyses (each branch writes its own key; `analyses` merges summaries)
    job_spec: dict[str, Any]
    risk_report: dict[str, Any]
    fit_report: dict[str, Any]
    analyses: Annotated[dict[str, Any], merge_dict]
    evidence: list[dict[str, Any]]
    # decision + downstream
    decision: dict[str, Any]
    price_quote: dict[str, Any]
    drafts: Annotated[list[dict[str, Any]], operator.add]
    verification: dict[str, Any]
    critiques: Annotated[list[dict[str, Any]], operator.add]
    compliance_verdict: dict[str, Any]
    dry_run: dict[str, Any]
    approvals: Annotated[list[dict[str, Any]], operator.add]
    submission: dict[str, Any]
    outcome: dict[str, Any]
    memory_used: dict[str, Any]
    # control
    revisions: int
    status: Annotated[str, merge_status]  # running | skipped | watch | awaiting_approval | submitted | rejected | blocked | needs_attention | dead_letter
    attention_reason: Annotated[str, last_nonempty]
    steps: Annotated[int, operator.add]
    usage: Annotated[list[dict[str, Any]], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]


class ConversationState(TypedDict, total=False):
    user_id: str
    persona: str
    thread_id: str
    trace_id: str
    proposal_id: str
    job: dict[str, Any]
    messages: list[dict[str, Any]]
    last_client_message: dict[str, Any]
    intent: dict[str, Any]
    slots: list[dict[str, Any]]
    reply: dict[str, Any]
    compliance_verdict: dict[str, Any]
    approvals: Annotated[list[dict[str, Any]], operator.add]
    sent: dict[str, Any]
    status: str
    steps: Annotated[int, operator.add]
    usage: Annotated[list[dict[str, Any]], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
