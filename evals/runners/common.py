"""Shared eval helpers: dataset loading, gold relevance, IR metrics, result writing."""
from __future__ import annotations

import json
import math
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"
PERSONAS = ["ai_ml", "fullstack", "data_analyst"]
GENERIC = {"Python", "JavaScript", "SQL", "HTML/CSS", "Data Analysis", "REST API", "Machine Learning", "KPI Reporting"}


def load_jobs(persona: str, split: str = "dev") -> list[dict[str, Any]]:
    p = ROOT / ("evals/datasets" if split == "dev" else "data/processed") / f"{split}_{persona}.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def facts(persona: str) -> dict[str, Any]:
    return json.loads((ROOT / "data" / "personas" / persona / "facts.json").read_text(encoding="utf-8"))


def gold_relevance(job: dict[str, Any], persona_facts: dict[str, Any]) -> dict[str, float]:
    """Graded relevance per project: specific skills weigh 1, ubiquitous ones 0.25. Gold set = rel >= min(1, max rel)."""
    jsk = set(job["gold"]["gold_skills"])
    rel = {}
    for p in persona_facts["projects"]:
        ov = jsk & set(p["all_skills"])
        r = sum(0.25 if s in GENERIC else 1.0 for s in ov)
        if r > 0:
            rel[p["project_id"]] = r
    if not rel:
        return {}
    thr = min(1.0, max(rel.values()))
    return {k: v for k, v in rel.items() if v >= thr}


def recall_at(ranked: list[str], gold: dict[str, float], k: int) -> float:
    if not gold:
        return float("nan")
    return len(set(ranked[:k]) & set(gold)) / min(k, len(gold))


def mrr(ranked: list[str], gold: dict[str, float]) -> float:
    for i, r in enumerate(ranked):
        if r in gold:
            return 1 / (i + 1)
    return 0.0


def ndcg_at(ranked: list[str], gold: dict[str, float], k: int) -> float:
    dcg = sum((2 ** gold.get(r, 0) - 1) / math.log2(i + 2) for i, r in enumerate(ranked[:k]))
    ideal = sorted(gold.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else float("nan")


def pct(values: list[float], q: float) -> float:
    v = sorted(x for x in values if x == x)
    if not v:
        return float("nan")
    i = min(len(v) - 1, max(0, math.ceil(q / 100 * len(v)) - 1))
    return v[i]


def mean(values: list[float]) -> float:
    v = [x for x in values if x == x]
    return sum(v) / len(v) if v else float("nan")


def env_info() -> dict[str, Any]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        commit = "uncommitted"
    return {"commit": commit, "machine": platform.processor() or platform.machine(), "python": platform.python_version(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}


def write(name: str, payload: dict[str, Any]) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / name
    p.write_text(json.dumps({"env": env_info(), **payload}, indent=2, default=str), encoding="utf-8")
    print("wrote", p.relative_to(ROOT))
    return p
