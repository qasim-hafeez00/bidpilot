"""Composable retrieval pipeline. Each RAG variant is a preset of these flags, so the ablation in
evals/runners/ablation.py can switch one component off at a time.

flags:
  scheme        fixed | structured | contextual       (indexing)
  query         whole | decomposed | hyde              (query transformation)
  hybrid        bool  BM25 + dense with reciprocal rank fusion
  rerank        bool  cross-encoder (bge/MiniLM) over the fused candidates
  multivector   bool  summary / README / code chunks scored separately and returned as one project
  outcome_boost float boost projects cited by proposals that won or got replies
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from rag.index.models import embed, rerank
from rag.index.store import get_index
from rag.ingest.loaders import PERSONA_ROOT
from rag.requirements import Requirement, decompose

RRF_K = 60
TYPES_EVIDENCE = {"case_study", "readme", "code", "review", "proposal"}


@dataclass
class Flags:
    scheme: str = "structured"
    query: str = "whole"
    hybrid: bool = False
    rerank: bool = False
    multivector: bool = False
    outcome_boost: float = 0.0
    crag: bool = False
    cand: int = 40

    @classmethod
    def of(cls, d: dict[str, Any]) -> Flags:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ProjectHit:
    project_id: str
    score: float
    chunks: list[dict[str, Any]] = field(default_factory=list)
    support: dict[str, float] = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)

    def as_evidence(self) -> list[dict[str, Any]]:
        return self.chunks


@lru_cache(maxsize=8)
def outcome_prior(persona: str) -> dict[str, float]:
    p = PERSONA_ROOT / persona / "proposals.json"
    if not p.exists():
        return {}
    agg: dict[str, list[float]] = defaultdict(list)
    for r in json.loads(p.read_text(encoding="utf-8")):
        if r.get("cited_project_id"):
            agg[r["cited_project_id"]].append({"won": 1.0, "replied": 0.5}.get(r["outcome"], 0.0))
    return {k: (sum(v) + 0.2) / (len(v) + 2) for k, v in agg.items()}


def _rrf(lists: list[list[tuple[int, float]]], weights: list[float] | None = None) -> dict[int, float]:
    out: dict[int, float] = defaultdict(float)
    for li, lst in enumerate(lists):
        w = weights[li] if weights else 1.0
        for rank, (i, _) in enumerate(lst):
            out[i] += w / (RRF_K + rank + 1)
    return out


def _queries(job: dict[str, Any], flags: Flags, hyde_text: str | None) -> list[tuple[str, Requirement | None]]:
    whole = f"{job.get('title', '')}\n{job.get('description', '')[:1500]}"
    if flags.query == "decomposed":
        return [(r.query, r) for r in decompose(job.get("title", ""), job.get("description", ""))]
    if flags.query == "hyde" and hyde_text:
        return [(hyde_text, None), (whole, None)]
    return [(whole, None)]


def chunk_scores(persona: str, query: str, flags: Flags, types: set[str] | None = None) -> list[tuple[int, float]]:
    idx = get_index(persona, flags.scheme)
    qv = embed([query], is_query=True)[0]
    dense = idx.dense(qv, flags.cand, types)
    if flags.hybrid:
        fused = _rrf([dense, idx.sparse(query, flags.cand, types)])
        ranked = sorted(fused.items(), key=lambda kv: -kv[1])[: flags.cand]
    else:
        ranked = dense
    if flags.rerank and ranked:
        top = ranked[:30]
        probs = rerank(query, [idx.chunks[i].text[:1200] for i, _ in top])
        ranked = sorted(zip([i for i, _ in top], probs.tolist(), strict=True), key=lambda kv: -kv[1])
    return ranked


def retrieve(job: dict[str, Any], persona: str, flags: Flags, k: int = 10, hyde_text: str | None = None,
             filters: dict[str, Any] | None = None) -> list[ProjectHit]:
    idx = get_index(persona, flags.scheme)
    types = set(filters["types"]) if filters and filters.get("types") else None
    per_query = []
    for q, req in _queries(job, flags, hyde_text):
        per_query.append((req, chunk_scores(persona, q, flags, types)))

    # merge across queries (RRF) - one retrieval per requirement then merge (V1)
    if len(per_query) > 1:
        fused = _rrf([r for _, r in per_query])
        chunk_score = dict(fused)
    else:
        lst = per_query[0][1]
        chunk_score = {i: s if flags.rerank else 1 / (RRF_K + rank + 1) for rank, (i, s) in enumerate(lst)}
        if not flags.rerank and not flags.hybrid:
            chunk_score = {i: s for i, s in lst}

    req_hits: dict[int, list[str]] = defaultdict(list)
    for req, lst in per_query:
        if req:
            for i, _ in lst[:5]:
                req_hits[i].append(req.skill or req.text[:60])

    by_proj: dict[str, dict[str, Any]] = {}
    for i, s in chunk_score.items():
        c = idx.chunks[i]
        pid = c.meta.get("project_id")
        if not pid or c.meta.get("type") not in TYPES_EVIDENCE:
            continue
        if filters and filters.get("outcome") and c.meta.get("type") == "proposal" and c.meta.get("outcome") not in filters["outcome"]:
            continue
        e = by_proj.setdefault(pid, {"per_type": defaultdict(float), "chunks": [], "reqs": set()})
        t = c.meta["type"]
        e["per_type"][t] = max(e["per_type"][t], s)
        e["chunks"].append((s, i))
        e["reqs"].update(req_hits.get(i, []))

    prior = outcome_prior(persona) if flags.outcome_boost else {}
    hits = []
    for pid, e in by_proj.items():
        if flags.multivector:
            score = sum(sorted(e["per_type"].values(), reverse=True)[:3])
        else:
            score = max(e["per_type"].values())
        if flags.outcome_boost:
            score *= 1 + flags.outcome_boost * prior.get(pid, 0.0)
        e["chunks"].sort(key=lambda t: -t[0])
        chunks = []
        for s, i in e["chunks"][:3]:
            c = idx.chunks[i]
            chunks.append({"evidence_id": c.meta.get("evidence_id"), "chunk_id": c.chunk_id, "type": c.meta.get("type"),
                           "title": c.meta.get("title"), "source": c.meta.get("source"), "date": c.meta.get("date"),
                           "outcome": c.meta.get("outcome"), "client_industry": c.meta.get("client_industry"),
                           "skills": c.meta.get("skills", []), "text": c.text[:900], "score": round(float(s), 5)})
        hits.append(ProjectHit(pid, float(score), chunks, dict(e["per_type"]), sorted(e["reqs"])))
    hits.sort(key=lambda h: -h.score)
    return hits[:k]
