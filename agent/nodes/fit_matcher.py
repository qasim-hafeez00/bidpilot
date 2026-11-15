"""Fit Matcher: map every requirement to portfolio evidence (Portfolio MCP, read) -> fit score with reasons.

Runs in parallel with the Analyst, so it decomposes requirements itself (same deterministic decomposer).
Strength per requirement: strong if an evidence item's metadata carries the skill or cross-encoder relevance >= hi;
partial if relevance >= lo; none otherwise (the Writer is told not to claim `none` requirements).
"""
from __future__ import annotations

import asyncio
from typing import Any

from agent.handoffs import FitReport, RequirementEvidence
from agent.nodes._util import rec, strip_injections, toolbox, trace_id
from common import config as cfg
from rag.requirements import decompose


async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    job = state["job"]
    tid = trace_id(state, config)
    tb = toolbox(config)
    reqs = decompose(job.get("title", ""), strip_injections(job.get("description", "")), max_req=7)
    hi, lo = cfg.get("thresholds.verify_support", 0.30), cfg.get("thresholds.verify_partial", 0.08)

    async def one(r):
        res = await tb.call("fit_matcher", "search_evidence", {"requirement": r.query[:600], "k": 3}, tid)
        return r, res["items"]

    results = await asyncio.gather(*(one(r) for r in reqs))
    matrix, evidence, seen = [], [], set()
    num = den = 0.0
    for r, items in results:
        strong = [i for i in items if (r.skill and r.skill in (i.get("skills") or [])) or i["relevance"] >= hi]
        partial = [i for i in items if i not in strong and i["relevance"] >= lo]
        use = strong or partial
        strength = "strong" if strong else "partial" if partial else "none"
        matrix.append(RequirementEvidence(requirement=r.text[:200], skill=r.skill, core=r.core,
                                          evidence_ids=[i["evidence_id"] for i in use[:3]],
                                          project_ids=sorted({i["project_id"] for i in use[:3] if i.get("project_id")}),
                                          strength=strength))
        w = 2.0 if r.core else 1.0 if r.skill else 0.5  # sentence-only requirements count half
        num += w * {"strong": 1.0, "partial": 0.5, "none": 0.0}[strength]
        den += w
        for i in use[:2]:
            if i["evidence_id"] not in seen:
                seen.add(i["evidence_id"])
                evidence.append(i)
    score = num / den if den else 0.0
    core_missing = [m.skill or m.requirement for m in matrix if m.core and m.strength == "none"]
    if core_missing:
        score = min(score, 0.35)  # cannot credibly bid without the core requirement
    matched = sorted({m.skill for m in matrix if m.skill and m.strength != "none"})
    missing = sorted({m.skill or m.requirement[:60] for m in matrix if m.strength == "none"})
    reasons = [f"{sum(m.strength == 'strong' for m in matrix)}/{len(matrix)} requirements strongly evidenced"]
    if core_missing:
        reasons.append(f"core requirement without evidence: {core_missing}")
    report = FitReport(score=round(score, 3), matched_skills=matched, missing_skills=missing,
                       evidence_ids=[e["evidence_id"] for e in evidence], matrix=matrix, reasons=reasons)
    return {"fit_report": report.model_dump(), "evidence": evidence[:10], "analyses": {"fit": "done"}, "steps": 1,
            "trace": [rec("fit_matcher", tool="search_evidence", calls=len(reqs), score=report.score, missing=missing)]}
