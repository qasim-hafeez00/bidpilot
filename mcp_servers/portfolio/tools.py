"""Portfolio tools (read-only). Pydantic schemas give the MCP input AND output schemas."""
from __future__ import annotations

import json
from collections import Counter
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from common.skills import extract_skills
from mcp_servers.common import AuditLog, current_identity
from rag import retriever
from rag.ingest.loaders import PERSONA_ROOT, load_persona

audit = AuditLog("portfolio")
EvidenceType = Literal["case_study", "readme", "code", "review", "proposal", "cv"]


class EvidenceFilters(BaseModel):
    persona: str | None = Field(None, description="Portfolio owner id; defaults to the caller's portfolio.")
    types: list[EvidenceType] | None = Field(None, description="Restrict to these evidence types.")
    outcome: list[Literal["won", "replied", "ignored"]] | None = Field(None, description="For past proposals only.")
    since: str | None = Field(None, pattern=r"^\d{4}(-\d{2})?(-\d{2})?$", description="Only evidence dated on/after YYYY[-MM[-DD]].")


class EvidenceItem(BaseModel):
    evidence_id: str
    project_id: str | None
    type: str
    title: str | None
    source: str | None
    date: str | None
    outcome: str | None
    client_industry: str | None
    skills: list[str]
    snippet: str
    score: float = Field(description="Retrieval rank score (variant-specific, comparable within one response).")
    relevance: float = Field(description="Cross-encoder probability that this item proves the requirement (0-1).")


class SearchEvidenceResult(BaseModel):
    requirement: str
    variant: str
    items: list[EvidenceItem]


class CaseStudy(BaseModel):
    id: str
    title: str
    markdown: str
    skills: list[str]
    client_industry: str | None
    date: str | None
    related_evidence_ids: list[str]


class SkillCount(BaseModel):
    skill: str
    evidence_count: int
    last_used: str | None


class SkillsResult(BaseModel):
    persona: str
    skills: list[SkillCount]


def _persona(filters: EvidenceFilters | None) -> str:
    ident = current_identity()
    want = (filters.persona if filters else None) or ident.get("persona")
    # tenant scoping: an HTTP caller may only read its own portfolio
    if ident.get("user_id") not in ("local-dev",) and ident.get("persona") and want != ident["persona"]:
        raise PermissionError("filters.persona does not match the caller's portfolio")
    return want


def search_evidence(
    requirement: Annotated[str, Field(min_length=3, max_length=2000, description="One job requirement or a whole job post.")],
    k: Annotated[int, Field(ge=1, le=20, description="Number of evidence items to return.")] = 5,
    filters: EvidenceFilters | None = None,
    trace_id: Annotated[str | None, Field(description="Trace id propagated from the UI request.")] = None,
) -> SearchEvidenceResult:
    """Find portfolio evidence (case studies, repos/code, reviews, past proposals with outcomes) that proves a requirement.
    Returns items with type, source, date and outcome so a proposal can cite them."""
    persona = _persona(filters)
    hits = retriever.retrieve_requirement(requirement, persona, k=max(k, 5),
                                          filters={"types": filters.types, "outcome": filters.outcome} if filters else None)
    items: list[EvidenceItem] = []
    for h in hits:
        for c in h.chunks[:2]:
            if filters and filters.since and (c.get("date") or "0") < filters.since:
                continue
            items.append(EvidenceItem(evidence_id=c["evidence_id"], project_id=h.project_id, type=c["type"], title=c.get("title"),
                                      source=c.get("source"), date=c.get("date"), outcome=c.get("outcome"),
                                      client_industry=c.get("client_industry"), skills=c.get("skills") or [],
                                      snippet=c["text"][:600], score=round(h.score, 5), relevance=0.0))
            break
        if len(items) >= k:
            break
    if items:
        from rag.index.models import rerank

        rel = rerank(requirement[:500], [f"{i.title}. {i.snippet} Skills: {', '.join(i.skills)}" for i in items])
        for i, r in zip(items, rel.tolist(), strict=True):
            i.relevance = round(float(r), 4)
    res = SearchEvidenceResult(requirement=requirement, variant=retriever.get().__name__.rsplit(".", 1)[-1], items=items)
    audit.write("search_evidence", {"requirement": requirement[:200], "k": k, "persona": persona}, {"n": len(items)}, trace_id)
    return res


def _find_doc(case_id: str):
    persona = case_id.split(":", 1)[0]
    if persona not in {p.name for p in PERSONA_ROOT.iterdir() if p.is_dir()}:
        persona = current_identity().get("persona")
    docs = load_persona(persona)
    return persona, docs, next((d for d in docs if case_id in (d.doc_id, d.meta.get("evidence_id"), d.meta.get("project_id"))
                                and d.meta["type"] in ("case_study", "readme", "review", "proposal")), None)


def get_case_study(id: Annotated[str, Field(min_length=3, max_length=200, description="Case-study, project or evidence id.")],
                   trace_id: str | None = None) -> CaseStudy:
    """Load one full case study (Markdown) by id, plus the ids of related evidence (repo, reviews, proposals)."""
    persona, docs, d = _find_doc(id)
    if d is None or (d.meta["type"] != "case_study" and not (d := next((x for x in docs if x.meta["type"] == "case_study"
                                                                         and x.meta.get("project_id") == d.meta.get("project_id")), None))):
        raise ValueError(f"case study not found: {id}")
    if persona != current_identity().get("persona") and current_identity().get("user_id") != "local-dev":
        raise PermissionError("not your portfolio")
    related = sorted({x.meta["evidence_id"] for x in docs if x.meta.get("project_id") == d.meta["project_id"] and x is not d})
    audit.write("get_case_study", {"id": id}, {"found": True}, trace_id)
    return CaseStudy(id=d.meta["project_id"], title=d.meta["title"], markdown=d.text, skills=d.meta.get("skills") or [],
                     client_industry=d.meta.get("client_industry"), date=d.meta.get("date"), related_evidence_ids=related)


def list_skills(persona: str | None = None, trace_id: str | None = None) -> SkillsResult:
    """List every skill evidenced anywhere in the portfolio (including skills only visible in code), with counts."""
    p = _persona(EvidenceFilters(persona=persona))
    cnt: Counter[str] = Counter()
    last: dict[str, str] = {}
    for d in load_persona(p):
        if d.meta["type"] == "proposal":
            continue
        for s in set(d.meta.get("skills") or extract_skills(d.text)):
            cnt[s] += 1
            if d.meta.get("date"):
                last[s] = max(last.get(s, ""), d.meta["date"])
    audit.write("list_skills", {"persona": p}, {"n": len(cnt)}, trace_id)
    return SkillsResult(persona=p, skills=[SkillCount(skill=s, evidence_count=n, last_used=last.get(s)) for s, n in cnt.most_common()])


def proposal_json(proposal_id: str) -> str:
    persona = proposal_id.split(":", 1)[0]
    data = json.loads((PERSONA_ROOT / persona / "proposals.json").read_text(encoding="utf-8"))
    rec = next((r for r in data if r["proposal_id"] == proposal_id), None)
    if not rec:
        raise ValueError(f"proposal not found: {proposal_id}")
    return json.dumps(rec, indent=2)
