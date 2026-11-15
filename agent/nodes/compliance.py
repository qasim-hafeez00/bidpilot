"""Compliance Guard: enforce the policy pack (rules live in agent/config.yaml `policy`, versioned with the GigSim policy).

Removes contact details, links (policy v2), off-platform apps/payment, guarantees, free-work offers and any echo of
instructions injected in the job post; blocks when a rule's action is `block` or nothing usable is left. No MCP access.
"""
from __future__ import annotations

import re
from typing import Any

from agent.handoffs import ComplianceVerdict
from agent.nodes._util import rec
from common import config as cfg

SENT = re.compile(r"(?<=[.!?])\s+")
ECHO_TOKENS = re.compile(r"\bBANANA\b|\$5\b|first[- ]page google ranking|100% success rate", re.I)


def check_text(text: str, injection_detected: bool = False) -> tuple[str, list[dict[str, Any]], bool]:
    rules = cfg.policy_rules()
    violations: list[dict[str, Any]] = []
    blocked = False
    kept = []
    for sent in SENT.split(text or ""):
        hit = None
        for r in rules:
            if re.search(r["pattern"], sent, re.I):
                hit = r
                break
        if hit is None and injection_detected and ECHO_TOKENS.search(sent):
            hit = {"id": "injection_echo", "action": "remove", "message": "Sentence follows an instruction injected in the job post."}
        if hit:
            violations.append({"rule": hit["id"], "action": hit["action"], "message": hit["message"], "sentence": sent[:200]})
            blocked = blocked or hit["action"] == "block"
        else:
            kept.append(sent)
    return " ".join(kept).strip(), violations, blocked


def evaluate(cover: str, answers: list[str], injection_detected: bool = False) -> ComplianceVerdict:
    fixed, v, blocked = check_text(cover, injection_detected)
    fixed_answers = []
    for a in answers:
        fa, va, ba = check_text(a, injection_detected)
        v += va
        blocked = blocked or ba
        fixed_answers.append(fa)
    if blocked or len(fixed.split()) < 25:
        reason = "blocked by policy: " + "; ".join(sorted({x["message"] for x in v if x["action"] == "block"})) if blocked else \
                 "too little compliant text left after removing violations"
        return ComplianceVerdict(status="block", violations=v, fixed_text=fixed, reason=reason)
    status = "fixed" if v else "pass"
    return ComplianceVerdict(status=status, violations=v, fixed_text=fixed if v else None,
                             reason="; ".join(sorted({x["message"] for x in v})) if v else "")


async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    draft = dict(state["drafts"][-1])
    inj = bool(state.get("risk_report", {}).get("injection_detected"))
    verdict = evaluate(draft["cover_letter"], draft.get("screening_answers", []), inj)
    out: dict[str, Any] = {"compliance_verdict": verdict.model_dump(), "steps": 1,
                           "trace": [rec("compliance", status=verdict.status, violations=[v["rule"] for v in verdict.violations])]}
    if verdict.status == "fixed":
        draft["cover_letter"] = verdict.fixed_text
        draft["screening_answers"] = [check_text(a, inj)[0] for a in draft.get("screening_answers", [])]
        draft["compliance_fixed"] = True
        out["drafts"] = [draft]
    if verdict.status == "block":
        out["status"] = "blocked"
        out["attention_reason"] = verdict.reason
    return out
