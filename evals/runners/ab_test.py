"""X2: proposal A/B experiment in GigSim - problem-first vs question-first openings, same jobs, separate accounts.
Two-proportion z-test and Fisher's exact test on reply rate.

    python -m evals.runners.ab_test --per-persona 6
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys

from evals.runners.common import RESULTS, write


def two_prop_z(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) if 0 < p < 1 else 0
    z = ((x1 / n1) - (x2 / n2)) / se if se else 0.0
    return z, math.erfc(abs(z) / math.sqrt(2))


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    n1, n2, k = a + b, c + d, a + c

    def pr(x: int) -> float:
        return math.comb(n1, x) * math.comb(n2, k - x) / math.comb(n1 + n2, k)

    obs = pr(a)
    return min(1.0, sum(pr(x) for x in range(max(0, k - n2), min(k, n1) + 1) if pr(x) <= obs + 1e-12))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=6)
    a = ap.parse_args()
    subprocess.run([sys.executable, "-m", "evals.runners.gigsim_outcomes", "--configs", "armA:best:problem_first,armB:best:question_first",
                    "--per-persona", str(a.per_persona), "--out", "ab_runs.json"], check=True)
    rows = [json.loads(x) for x in (RESULTS / "ab_runs_rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rep = {arm: [r for r in rows if r["config"] == arm and r.get("reply_status")] for arm in ("armA", "armB")}
    xa = sum(r["reply_status"] in ("replied", "interview", "hired") for r in rep["armA"])
    xb = sum(r["reply_status"] in ("replied", "interview", "hired") for r in rep["armB"])
    na, nb = len(rep["armA"]), len(rep["armB"])
    z, pz = two_prop_z(xa, na, xb, nb) if na and nb else (0.0, 1.0)
    pf = fisher_two_sided(xa, na - xa, xb, nb - xb) if na and nb else 1.0
    out = {"arms": {"A_problem_first": {"n": na, "replies": xa, "rate": round(xa / na, 3) if na else None},
                    "B_question_first": {"n": nb, "replies": xb, "rate": round(xb / nb, 3) if nb else None}},
           "z": round(z, 3), "p_two_prop_z": round(pz, 4), "p_fisher": round(pf, 4), "significant_at_0.05": pf < 0.05,
           "note": "GigSim clients use the rule model unless GIGSIM_CLIENT_MODE=llm; reply rate measures fit to that model."}
    print(out)
    write("ab_test.json", out)


if __name__ == "__main__":
    main()
