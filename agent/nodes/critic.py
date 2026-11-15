"""Critic: grounding, personalisation, length, screening answers, citations. Sends the draft back with reasons
(at most `budgets.max_revisions` times). Rules always run; an LLM personalisation check is optional (config)."""
from __future__ import annotations

import re
from typing import Any

from agent.handoffs import Critique
from agent.nodes._util import rec
from common import config as cfg
from common.llm import LLMUnavailable, chat, parse_json
from rag.verify import strip_markers

GENERIC = re.compile(r"^\s*(hi|hello|dear|greetings|i am|i'm|my name is|as an? )|passionate|hard[- ]?working|"
                     r"high[- ]quality work|look(ing)? forward to working|check my profile", re.I)


def rule_checks(draft: dict[str, Any], job: dict[str, Any], spec: dict[str, Any], verification: dict[str, Any],
                n_evidence: int) -> tuple[list[str], dict[str, float]]:
    issues: list[str] = []
    text = strip_markers(draft["cover_letter"])
    words = len(text.split())
    lo, hi = cfg.get("thresholds.proposal_words", [110, 260])
    before = verification.get("before", {})
    ratio = float(before.get("supported_ratio", 1.0))
    if ratio < cfg.get("thresholds.critic_min_supported_ratio", 0.8):
        issues.append(f"only {ratio:.0%} of claims were supported by evidence; removed: {verification.get('removed', [])[:2]}. "
                      "Claim only what the EVIDENCE shows and put an [E:id] marker after each claim.")
    first = " ".join(re.split(r"(?<=[.!?])\s+", text)[:2])
    if GENERIC.search(first) or len(GENERIC.findall(text)) >= 2:
        issues.append("generic opening or filler phrases; open with the client's specific problem")
    kws = {k.lower() for k in spec.get("core_skills", [])} | {w for w in re.findall(r"[a-z]{5,}", job.get("title", "").lower())}
    personal = sum(1 for k in kws if k in first.lower())
    if kws and personal == 0:
        issues.append(f"the first two sentences do not mention anything specific to this job ({sorted(kws)[:4]})")
    if words < lo:
        issues.append(f"too short ({words} words; aim for {lo}-{hi})")
    if words > hi:
        issues.append(f"too long ({words} words; max {hi})")
    qs = spec.get("screening_questions", [])
    if len([a for a in draft.get("screening_answers", []) if a.strip()]) < len(qs):
        issues.append(f"answer all {len(qs)} screening questions")
    cited = set(re.findall(r"\[E:([^\]]+)\]", draft["cover_letter"]))
    if n_evidence >= 2 and len(cited) < 2:
        issues.append("cite at least two different evidence items with [E:id] markers")
    scores = {"supported_ratio": ratio, "words": words, "personalisation_hits": personal, "citations": len(cited)}
    return issues, scores


async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    draft, job, spec = state["drafts"][-1], state["job"], state.get("job_spec", {})
    issues, scores = rule_checks(draft, job, spec, state.get("verification", {}), len(state.get("evidence", [])))
    usage = []
    if cfg.get("models.use_llm.critic", False) and not issues:
        try:
            r = await chat("critic", "critic", json_mode=True, max_tokens=200, config=config, title=job.get("title", ""),
                           summary="; ".join(spec.get("deliverables", [])[:3]), draft=strip_markers(draft["cover_letter"]),
                           rule_issues="none")
            usage.append(r.usage("critic"))
            d = parse_json(r.text)
            if d.get("generic") or d.get("addresses_client_problem") is False:
                issues.append(d.get("instructions") or "make the opening specific to the client's problem")
        except LLMUnavailable as e:
            usage.append({"node": "critic", "error": str(e)[:200]})
    c = Critique(passed=not issues, issues=issues, instructions=" ".join(f"({i + 1}) {x}" for i, x in enumerate(issues)), scores=scores)
    revisions = state.get("revisions", 0) + (0 if c.passed else 1)
    return {"critiques": [c.model_dump() | {"version": draft["version"]}], "revisions": revisions, "usage": usage, "steps": 1,
            "trace": [rec("critic", passed=c.passed, issues=issues, revision=revisions)]}
