"""Ablate the composite retrieval pipeline one component at a time (R&D question B).

    python -m evals.runners.ablation [--limit 0]
"""
from __future__ import annotations

import argparse
import time

from evals.runners.common import PERSONAS, facts, gold_relevance, load_jobs, mean, ndcg_at, recall_at, write
from rag.pipeline import Flags, retrieve
from rag.variants.best import PRESET

ABLATIONS = {
    "composite (all on)": {},
    "- decomposition": {"query": "whole"},
    "- hybrid (dense only)": {"hybrid": False},
    "- cross-encoder rerank": {"rerank": False},
    "- multi-vector": {"multivector": False},
    "- outcome boost": {"outcome_boost": 0.0},
    "- structured chunks (fixed)": {"scheme": "fixed"},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    rows, base = [], None
    for name, change in ABLATIONS.items():
        flags = Flags.of({**PRESET, **change})
        r5, nd, multi = [], [], []
        t0 = time.time()
        for p in PERSONAS:
            f = facts(p)
            for j in [j for j in load_jobs(p) if not j["gold"]["gold_scam"]][: a.limit or None]:
                gold = gold_relevance(j, f)
                if not gold:
                    continue
                ranked = [h.project_id for h in retrieve(j, p, flags, k=10)]
                r5.append(recall_at(ranked, gold, 5))
                nd.append(ndcg_at(ranked, gold, 10))
                if len(j["gold"]["gold_skills"]) >= 4:
                    multi.append(recall_at(ranked, gold, 5))
        row = {"config": name, "recall@5": round(mean(r5), 4), "ndcg@10": round(mean(nd), 4),
               "recall@5_multi_req": round(mean(multi), 4), "n": len(r5)}
        base = base or row
        row["delta_recall5_pts"] = round((row["recall@5"] - base["recall@5"]) * 100, 2)
        rows.append(row)
        print(f"{name:32s} R@5={row['recall@5']:.3f} nDCG={row['ndcg@10']:.3f} ({time.time() - t0:.0f}s)")
    write("ablation.json", {"limit": a.limit, "base_preset": PRESET, "rows": rows})


if __name__ == "__main__":
    main()
