"""Bid graph - one thread per job (hand-written StateGraph, R3 / C1).

  intake --Send--> analyst ---------\
         --Send--> risk_assessor -----> decide --skip/watch--> END
         --Send--> fit_matcher -----/          \--bid--> pricing -> writer -> verifier -> critic --fail (<=2)--> writer
                                                                                              \--pass--> compliance --block--> END
                                                       prepare_approval <-------------------------------------/
                                                       -> approval [interrupt] --approve/edit--> submit -> END
                                                                               --reject--> END
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agent.graphs._guard import guard, halted
from agent.memory.store import reply_rate_prior
from agent.nodes import (
    analyst,
    approval,
    compliance,
    critic,
    decision,
    fit_matcher,
    pricing,
    risk_assessor,
    verifier,
    writer,
)
from agent.nodes._util import rec, toolbox, trace_id, untrusted
from agent.state import BidState
from common import config as cfg


async def intake(state: dict[str, Any], config: dict[str, Any], *, store=None) -> dict[str, Any]:
    """Scout hand-off: load the job through the marketplace port (MCP), mask PII in untrusted text."""
    job = state.get("job")
    trace = []
    if not job or "description" not in job:
        job = await toolbox(config).call("intake", "get_job", {"job_id": state["job_id"]}, trace_id(state, config))
        trace.append(rec("intake", tool="get_job", job_id=state["job_id"]))
    job = {**job, "title": untrusted(job.get("title", "")), "description": untrusted(job.get("description", ""))}
    s = {"hourly_floor": 0, "min_fixed": 0, "weekly_connects_budget": 10**6, "connects_spent_this_week": 0, "autonomy": "suggest",
         **(state.get("settings") or {})}
    from common.skills import skill_domain

    dom = skill_domain((job.get("skills") or ["?"])[0])
    prior = await reply_rate_prior(store, state.get("user_id", "anon"), dom) if store else 0.15
    return {"job": job, "job_id": job["job_id"], "settings": s, "status": "running", "revisions": 0, "steps": 1,
            "memory_used": {"reply_rate_prior": prior}, "trace": trace + [rec("intake", title=job.get("title", "")[:80])]}


def fan_out(state: dict[str, Any]):
    if halted(state):
        return END
    return [Send("analyst", state), Send("risk_assessor", state), Send("fit_matcher", state)]


def after_decide(state: dict[str, Any]) -> str:
    if halted(state) or state.get("decision", {}).get("action") != "bid":
        return END
    if state.get("settings", {}).get("analysis_only"):
        return END
    return "pricing"


def nxt(target: str):
    def route(state: dict[str, Any]) -> str:
        return END if halted(state) else target
    route.__name__ = f"to_{target}"
    return route


def after_critic(state: dict[str, Any]) -> str:
    if halted(state):
        return END
    last = (state.get("critiques") or [{}])[-1]
    if last.get("passed"):
        return "compliance"
    if state.get("revisions", 0) <= cfg.get("budgets.max_revisions", 2):
        return "writer"
    return "compliance"  # loop limit reached: proceed, the unresolved critique is shown in the approval UI


def after_approval(state: dict[str, Any]) -> str:
    s = state.get("status")
    if s == "approved":
        return "submit"
    if s == "awaiting_approval":
        return "approval"
    return END


def build_bid_graph(checkpointer=None, store=None):
    g = StateGraph(BidState)
    g.add_node("intake", guard("intake", intake))
    g.add_node("analyst", guard("analyst", analyst.run))
    g.add_node("risk_assessor", guard("risk_assessor", risk_assessor.run))
    g.add_node("fit_matcher", guard("fit_matcher", fit_matcher.run))
    g.add_node("decide", guard("decide", decision.run))
    g.add_node("pricing", guard("pricing", pricing.run))
    g.add_node("writer", guard("writer", writer.run))
    g.add_node("verifier", guard("verifier", verifier.run))
    g.add_node("critic", guard("critic", critic.run))
    g.add_node("compliance", guard("compliance", compliance.run))
    g.add_node("prepare_approval", guard("prepare_approval", approval.prepare))
    g.add_node("approval", guard("approval", approval.approval))
    g.add_node("submit", guard("submit", approval.submit))

    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", fan_out, ["analyst", "risk_assessor", "fit_matcher", END])
    g.add_edge(["analyst", "risk_assessor", "fit_matcher"], "decide")
    g.add_conditional_edges("decide", after_decide, ["pricing", END])
    g.add_conditional_edges("pricing", nxt("writer"), ["writer", END])
    g.add_conditional_edges("writer", nxt("verifier"), ["verifier", END])
    g.add_conditional_edges("verifier", nxt("critic"), ["critic", END])
    g.add_conditional_edges("critic", after_critic, ["writer", "compliance", END])
    g.add_conditional_edges("compliance", nxt("prepare_approval"), ["prepare_approval", END])
    g.add_conditional_edges("prepare_approval", nxt("approval"), ["approval", END])
    g.add_conditional_edges("approval", after_approval, ["submit", "approval", END])
    g.add_edge("submit", END)
    return g.compile(checkpointer=checkpointer, store=store)
