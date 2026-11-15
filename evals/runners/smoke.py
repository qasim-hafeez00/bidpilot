"""CI smoke eval: 30 dev jobs (10 per persona) through the real graph (analysis-only) + claim verification on canned
drafts. Fails the build when bid-or-skip F1 drops or unsupported claims rise past the thresholds below."""
from __future__ import annotations

import asyncio
import sys

from evals.checkers.fact_check import check
from evals.runners.common import facts, write
from evals.runners.decision_eval import run_persona, summarize
from rag import verify

THRESHOLDS = {"min_bid_f1": 0.55, "min_scam_recall": 0.8, "max_unsupported_after_verification": 0.0}

CANNED = {  # a draft with one true and one fabricated claim per persona: verification must remove the fabricated one
    "ai_ml": "On the contract Q&A assistant I cut clause lookup time from 25 minutes to under 2 minutes [E:ai_ml:case:legal-rag]. "
             "I have also built Solidity smart contracts for 30 banks.",
    "fullstack": "My logistics REST API cut p95 latency from 2.4 s to 310 ms [E:fullstack:case:drf-api]. "
                 "I also led a 40-person Kubernetes team at a bank with 99% savings.",
    "data_analyst": "My sales dashboard is used by 45 managers [E:data_analyst:case:sales-powerbi]. "
                    "I have 12 years of SAP experience with 70% cost cuts.",
}


async def main() -> int:
    rows = []
    for p in ("ai_ml", "fullstack", "data_analyst"):
        rows += await run_persona(p, "dev", 10, concurrency=4)
    s = summarize(rows)["overall"]
    after = []
    from rag.ingest.loaders import load_persona

    for p, draft in CANNED.items():
        ev = [{"evidence_id": d.meta.get("evidence_id"), "project_id": d.meta.get("project_id"), "title": d.meta.get("title"),
               "text": d.text, "skills": d.meta.get("skills")} for d in load_persona(p) if d.meta["type"] == "case_study"]
        clean, _ = verify.apply(draft, verify.verify_claims(draft, ev))
        after.append(check(clean, facts(p))["unsupported"])
    res = {"bid_f1": s["bid_skip"]["f1"], "scam_recall": s["scam"]["recall"], "unsupported_after_verification": sum(after) / len(after)}
    ok = (res["bid_f1"] >= THRESHOLDS["min_bid_f1"] and res["scam_recall"] >= THRESHOLDS["min_scam_recall"]
          and res["unsupported_after_verification"] <= THRESHOLDS["max_unsupported_after_verification"])
    write("smoke.json", {"thresholds": THRESHOLDS, "results": res, "passed": ok})
    print(res, "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
