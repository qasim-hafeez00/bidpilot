"""Retrieval evaluation of every RAG variant: Recall@5, MRR, nDCG@10 vs gold evidence, per persona and job type.

    python -m evals.runners.rag_eval --variants v0,v1,v2,v3,v4,v5,v6,v8,best [--split dev] [--limit 0]
"""
from __future__ import annotations

import argparse
import csv
import time
from collections import defaultdict

from evals.runners.common import (
    PERSONAS,
    RESULTS,
    facts,
    gold_relevance,
    load_jobs,
    mean,
    mrr,
    ndcg_at,
    pct,
    recall_at,
    write,
)
from rag import retriever


def run_variant(variant: str, split: str, limit: int) -> dict:
    rows = []
    for persona in PERSONAS:
        f = facts(persona)
        jobs = load_jobs(persona, split)
        jobs = [j for j in jobs if not j["gold"]["gold_scam"]]
        if limit:
            jobs = jobs[:limit]
        for j in jobs:
            gold = gold_relevance(j, f)
            t0 = time.perf_counter()
            hits = retriever.retrieve(j, persona, k=10, variant=variant)
            dt = time.perf_counter() - t0
            ranked = [h.project_id for h in hits]
            rows.append({"persona": persona, "job_id": j["job_id"], "job_type": j["gold"]["job_type"],
                         "multi_req": len(j["gold"]["gold_skills"]) >= 4, "has_gold": bool(gold),
                         "gold_decision": j["gold"]["gold_decision"], "n_hits": len(hits),
                         "recall5": recall_at(ranked, gold, 5) if gold else float("nan"),
                         "mrr": mrr(ranked, gold) if gold else float("nan"),
                         "ndcg10": ndcg_at(ranked, gold, 10) if gold else float("nan"), "latency_s": dt})
    return summarize(variant, rows), rows


def summarize(variant: str, rows: list[dict]) -> dict:
    def agg(rs):
        g = [r for r in rs if r["has_gold"]]
        return {"n": len(g), "recall@5": round(mean([r["recall5"] for r in g]), 4), "mrr": round(mean([r["mrr"] for r in g]), 4),
                "ndcg@10": round(mean([r["ndcg10"] for r in g]), 4),
                "p50_latency_s": round(pct([r["latency_s"] for r in rs], 50), 4),
                "p95_latency_s": round(pct([r["latency_s"] for r in rs], 95), 4)}

    out = {"variant": variant, "overall": agg(rows), "by_persona": {}, "by_job_type": {}}
    groups = defaultdict(list)
    for r in rows:
        groups[r["persona"]].append(r)
    out["by_persona"] = {k: agg(v) for k, v in groups.items()}
    groups = defaultdict(list)
    for r in rows:
        groups["multi_req (>=4 skills)" if r["multi_req"] else "few_req (<4 skills)"].append(r)
        groups[r["job_type"].replace("_multi_req", "")].append(r)
    out["by_job_type"] = {k: agg(v) for k, v in groups.items()}
    # skip-jobs: does the retriever refuse (return nothing) when the persona should skip? (V8 property)
    skip = [r for r in rows if r["gold_decision"] == "skip" and not r["has_gold"]]
    out["refusal_rate_on_no_evidence_jobs"] = round(mean([1.0 if r["n_hits"] == 0 else 0.0 for r in skip]), 4) if skip else None
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="v0,v1,v2,v3,v4,v5,v6,v8,best")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="rag_variants.json")
    ap.add_argument("--merge", action="store_true", help="keep other variants already in --out")
    a = ap.parse_args()
    summaries, all_rows = [], []
    if a.merge and (RESULTS / a.out).exists():  # keep variants measured by an earlier run (same split and limit)
        import json

        prev = json.loads((RESULTS / a.out).read_text(encoding="utf-8"))
        todo = set(a.variants.split(","))
        summaries = [v for v in prev["variants"] if v["variant"] not in todo]
        with open(RESULTS / a.out.replace(".json", "_rows.csv"), encoding="utf-8") as fh:
            all_rows = [r for r in csv.DictReader(fh) if r["variant"] not in todo]
    for v in a.variants.split(","):
        t0 = time.time()
        s, rows = run_variant(v, a.split, a.limit)
        summaries.append(s)
        all_rows += [{"variant": v, **r} for r in rows]
        o = s["overall"]
        print(f"{v:5s} R@5={o['recall@5']:.3f} MRR={o['mrr']:.3f} nDCG@10={o['ndcg@10']:.3f} "
              f"p95={o['p95_latency_s']:.3f}s  ({time.time() - t0:.0f}s)", flush=True)
        # write after every variant so a long run is never lost
        write(a.out, {"split": a.split, "limit_per_persona": a.limit, "variants": summaries})
        with open(RESULTS / a.out.replace(".json", "_rows.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(all_rows[0].keys()))
            w.writeheader()
            w.writerows(all_rows)


if __name__ == "__main__":
    main()
