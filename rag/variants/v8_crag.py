"""V8 - Corrective RAG loop implemented as a LangGraph subgraph.

For every requirement: retrieve (hybrid + rerank) -> grade with the cross-encoder probability ->
  correct (>= hi)       keep evidence
  ambiguous             re-query once: alias-expanded query restricted to code/README chunks (where implied skills hide)
  incorrect (< lo)      refuse to claim: requirement marked unsupported, no evidence passed to the writer
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from common.skills import SKILLS
from rag.pipeline import Flags, ProjectHit, chunk_scores, retrieve
from rag.requirements import decompose

PRESET = {"scheme": "structured", "query": "decomposed", "hybrid": True, "rerank": True, "multivector": True,
          "outcome_boost": 0.3, "crag": True}
HI, LO = 0.30, 0.08


class CragState(TypedDict, total=False):
    job: dict[str, Any]
    persona: str
    pending: list[dict[str, Any]]
    graded: Annotated[list[dict[str, Any]], operator.add]
    round: int


def _grade_one(persona: str, query: str, flags: Flags, types: set[str] | None) -> tuple[float, list[int]]:
    ranked = chunk_scores(persona, query, flags, types)
    return (ranked[0][1] if ranked else 0.0), [i for i, _ in ranked[:3]]


def node_grade(state: CragState) -> dict[str, Any]:
    flags = Flags.of({**PRESET, "query": "whole"})
    out, retry = [], []
    for r in state["pending"]:
        best, idxs = _grade_one(state["persona"], r["query"], flags, r.get("types"))
        grade = "correct" if best >= HI else ("ambiguous" if best >= LO else "incorrect")
        if grade == "ambiguous" and state.get("round", 0) == 0:
            retry.append(r)
        else:
            out.append({**r, "grade": grade if grade != "ambiguous" else "partial", "best": round(best, 4), "chunks": idxs})
    return {"graded": out, "pending": retry, "round": state.get("round", 0) + 1}


def node_requery(state: CragState) -> dict[str, Any]:
    pend = []
    for r in state["pending"]:
        sk = r.get("skill")
        expanded = r["query"] if not sk else f"{sk} {' '.join(SKILLS.get(sk, [])[:6])} import"
        pend.append({**r, "query": expanded, "types": {"code", "readme"}})
    return {"pending": pend}


def _route(state: CragState) -> str:
    return "requery" if state.get("pending") else END


def build_crag_graph():
    g = StateGraph(CragState)
    g.add_node("grade", node_grade)
    g.add_node("requery", node_requery)
    g.add_edge(START, "grade")
    g.add_conditional_edges("grade", _route, {"requery": "requery", END: END})
    g.add_edge("requery", "grade")
    return g.compile()


_GRAPH = None


def assess(job: dict[str, Any], persona: str) -> list[dict[str, Any]]:
    global _GRAPH
    _GRAPH = _GRAPH or build_crag_graph()
    reqs = [{"text": r.text, "skill": r.skill, "core": r.core, "query": r.query, "types": None}
            for r in decompose(job.get("title", ""), job.get("description", ""))]
    res = _GRAPH.invoke({"job": job, "persona": persona, "pending": reqs, "graded": [], "round": 0})
    return res["graded"]


def retrieve_with(job: dict[str, Any], persona: str, k: int = 10, **kw: Any) -> list[ProjectHit]:
    graded = assess(job, persona)
    supported = [g for g in graded if g["grade"] != "incorrect"]
    if not supported:
        return []  # refuse: nothing to claim
    sub = {**job, "description": " ".join(g["text"] for g in supported)}
    hits = retrieve(sub, persona, Flags.of(PRESET), k=k, **kw)
    unsupported = {g.get("skill") or g["text"][:60] for g in graded if g["grade"] == "incorrect"}
    for h in hits:
        h.requirements = [r for r in h.requirements if r not in unsupported]
    return hits


def retrieve_variant(job: dict[str, Any], persona: str, k: int = 10, **kw: Any) -> list[ProjectHit]:
    return retrieve_with(job, persona, k=k, **kw)
