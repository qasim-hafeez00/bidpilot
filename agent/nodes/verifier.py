"""Claim verification node (B3): split the latest draft into claims, ground each against evidence, remove unsupported
claims BEFORE the Critic sees the draft. Records before/after statistics."""
from __future__ import annotations

from typing import Any

from agent.nodes._util import rec
from rag import verify


async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    draft = dict(state["drafts"][-1])
    pool = [{**e, "text": e.get("snippet", e.get("text", ""))} for e in state.get("evidence", [])]
    res_cover = verify.verify_claims(draft["cover_letter"], pool)
    clean_cover, removed = verify.apply(draft["cover_letter"], res_cover)
    clean_answers, ans_results = [], []
    for a in draft.get("screening_answers", []):
        ra = verify.verify_claims(a, pool)
        ans_results += ra
        ca, rem = verify.apply(a, ra)
        removed += rem
        clean_answers.append(ca or "I would be glad to walk you through my approach on a short call.")
    before = verify.stats(res_cover + ans_results)
    after = verify.stats(verify.verify_claims(clean_cover, pool)) if clean_cover else {"claims": 0, "unsupported": 0, "supported_ratio": 1.0}
    draft.update({"cover_letter": clean_cover, "screening_answers": clean_answers, "verified": True,
                  "raw_cover_letter": state["drafts"][-1]["cover_letter"]})
    claims = [{"text": r["text"], "label": r["label"], "evidence_id": r.get("evidence_id"), "score": r.get("score"),
               "missing": r.get("missing", [])} for r in res_cover + ans_results if r["label"] != "not_a_claim"]
    return {"drafts": [draft], "verification": {"before": before, "after": after, "removed": [r["text"] for r in removed],
                                                "claims": claims, "version": draft["version"]},
            "steps": 1, "trace": [rec("verifier", before=before, after=after, removed=len(removed))]}
