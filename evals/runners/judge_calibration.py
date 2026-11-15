"""LLM-judge scoring + calibration against human labels (Cohen's kappa, quadratic-weighted, on the 1-5 overall score).

1. Scores every proposal in evals/results/proposals_rows.jsonl with the judge model (profile tier `judge`).
2. Writes evals/datasets/judge_labels_template.csv with 30 proposals for a HUMAN to label (column human_overall, 1-5).
3. If evals/datasets/judge_labels.csv exists (the human's labels), computes kappa and reports judge scores as calibrated.
   Without human labels the judge scores are reported as UNCALIBRATED and must not be quoted as quality.
"""
from __future__ import annotations

import asyncio
import csv
import json
import random

from common.llm import LLMUnavailable, chat, parse_json
from evals.runners.common import RESULTS, ROOT, mean, write

LABELS = ROOT / "evals" / "datasets" / "judge_labels.csv"
TEMPLATE = ROOT / "evals" / "datasets" / "judge_labels_template.csv"


def kappa_quadratic(a: list[int], b: list[int], k: int = 5) -> float:
    n = len(a)
    if n == 0:
        return float("nan")
    o = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        o[x - 1][y - 1] += 1
    ha = [sum(1 for x in a if x == i + 1) for i in range(k)]
    hb = [sum(1 for y in b if y == i + 1) for i in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = ((i - j) ** 2) / ((k - 1) ** 2)
            num += w * o[i][j]
            den += w * ha[i] * hb[j] / n
    return 1 - num / den if den else float("nan")


async def main() -> None:
    src = RESULTS / "proposals_rows.jsonl"
    rows = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
    scored = []
    for r in rows:
        if not r.get("final_draft"):
            continue
        try:
            res = await chat("judge", "judge", tier="judge", json_mode=True, max_tokens=160, temperature=0.0,
                             job=r["job_text"][:1500], proposal=r["final_draft"][:2500])
            d = parse_json(res.text)
            scored.append({"key": f"{r['config']}:{r['job_id']}", "config": r["config"], "overall": int(d.get("overall", 0) or 0),
                           **{k: d.get(k) for k in ("relevance", "specificity", "personalisation", "professionalism", "reason")}})
            print(scored[-1]["key"], scored[-1]["overall"], flush=True)
        except (LLMUnavailable, ValueError) as e:
            print("judge failed", r["job_id"], e)
    by_cfg = {}
    for c in sorted({s["config"] for s in scored}):
        by_cfg[c] = round(mean([s["overall"] for s in scored if s["config"] == c and s["overall"]]), 3)
    # labelling sheet for the human (blind: config hidden)
    pool = [r for r in rows if r.get("final_draft")]
    random.Random(7).shuffle(pool)
    with open(TEMPLATE, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "job_title", "proposal", "human_overall (1-5)"])
        for r in pool[:30]:
            w.writerow([f"{r['config']}:{r['job_id']}", r["title"], r["final_draft"], ""])
    calib = {"status": "uncalibrated - no human labels yet", "kappa_quadratic": None, "n": 0}
    if LABELS.exists():
        human = {row["key"]: int(row["human_overall (1-5)"]) for row in csv.DictReader(open(LABELS, encoding="utf-8")) if row.get("human_overall (1-5)")}
        pairs = [(human[s["key"]], s["overall"]) for s in scored if s["key"] in human and 1 <= s["overall"] <= 5]
        k = kappa_quadratic([a for a, _ in pairs], [b for _, b in pairs])
        calib = {"status": "calibrated" if k == k and k >= 0.4 else "judge disagrees with human labels", "kappa_quadratic": round(k, 3),
                 "n": len(pairs), "disagreements": [{"key": s["key"], "judge": s["overall"], "human": human[s["key"]]}
                                                    for s in scored if s["key"] in human and abs(human[s["key"]] - s["overall"]) >= 2]}
    write("judge.json", {"mean_overall_by_config": by_cfg, "calibration": calib, "scores": scored})


if __name__ == "__main__":
    asyncio.run(main())
