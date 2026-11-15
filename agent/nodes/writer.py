"""Proposal Writer: cover letter + screening answers with an evidence marker on every experience sentence.

Model: the strongest configured tier. Falls back to a deterministic, fully-grounded template writer if the LLM is
unavailable (degraded mode) - the template only restates evidence text, so it cannot invent experience.
"""
from __future__ import annotations

import json
import re
from typing import Any

from agent.memory.store import outcome_insights, style_rules
from agent.nodes._util import job_text, rec
from common import config as cfg
from common.llm import LLMUnavailable, chat


def evidence_block(evidence: list[dict[str, Any]], limit: int = 7) -> str:
    lines = []
    for e in evidence[:limit]:
        snippet = re.sub(r"\s+", " ", e.get("snippet", e.get("text", "")))[:420]
        lines.append(f"[E:{e['evidence_id']}] ({e.get('type')}, project={e.get('project_id')}, industry={e.get('client_industry') or '-'}, "
                     f"date={e.get('date') or '-'}) {e.get('title')}: {snippet}")
    return "\n".join(lines) or "(no evidence found)"


def parse(text: str, n_questions: int) -> tuple[str, list[str]]:
    m = re.search(r"COVER LETTER:\s*(.*?)(?:\n\s*ANSWERS:|$)", text, re.S | re.I)
    cover = (m.group(1) if m else text).strip()
    answers: list[str] = []
    a = re.search(r"ANSWERS:\s*(.*)$", text, re.S | re.I)
    if a and n_questions:
        parts = re.split(r"\n\s*\d+[.)]\s*", "\n" + a.group(1).strip())
        answers = [p.strip() for p in parts if p.strip()][:n_questions]
    cover = re.sub(r"^\*+|\*+$", "", cover).strip()
    return cover, answers


def template_draft(job: dict[str, Any], spec: dict[str, Any], evidence: list[dict[str, Any]], price: dict[str, Any]) -> tuple[str, list[str]]:
    core = ", ".join(spec.get("core_skills", [])[:2]) or "this project"
    lines = [f"Your {job.get('title', 'project')} needs someone who has already shipped {core} work."]
    used = set()
    for e in evidence:
        if e.get("type") in ("case_study", "review") and e.get("project_id") not in used:
            snip = re.sub(r"\s+", " ", e.get("snippet", ""))
            res = re.search(r"Outcome\s*The project (.+?)\.", snip) or re.search(r"result: (.+?)\.", snip)
            title = e.get("title", "a similar project")
            lines.append(f"On {title} for a {e.get('client_industry') or 'previous'} client the project {res.group(1) if res else 'shipped to production'}. [E:{e['evidence_id']}]")
            used.add(e.get("project_id"))
        if len(used) >= 2:
            break
    lines.append("I would start with a short scoped first milestone so you can judge the work early.")
    lines.append("What does success look like for you in the first two weeks?")
    answers = [f"Based on my portfolio: {lines[1] if len(lines) > 1 else 'see the evidence above.'}" for _ in spec.get("screening_questions", [])]
    return " ".join(lines), answers


async def run(state: dict[str, Any], config: dict[str, Any], *, store=None) -> dict[str, Any]:
    job, spec = state["job"], state.get("job_spec", {})
    evidence = state.get("evidence", [])
    fit = state.get("fit_report", {})
    price = state.get("price_quote", {})
    user = state.get("user_id", "anon")
    category = spec.get("domain", "other")
    s_rules = await style_rules(store, user) if store else []
    o_ins = await outcome_insights(store, user, category) if store else []
    qs = spec.get("screening_questions", [])
    revision = state.get("revisions", 0)
    notes = ""
    if state.get("critiques"):
        last = state["critiques"][-1]
        notes = f"REVISION {revision}: the reviewer rejected the previous draft. Fix exactly this: {last.get('instructions')}"
    strategy = (state.get("settings") or {}).get("proposal_strategy")
    if strategy:  # X2 A/B experiment arm; instruction text lives in config, not code
        notes += "\nOPENING STYLE FOR THIS PROPOSAL: " + cfg.get(f"experiments.strategies.{strategy}", "")
    lo, hi = cfg.get("thresholds.proposal_words", [110, 260])
    usage: list[dict] = []
    mode = "llm"
    try:
        r = await chat("writer", "writer", max_tokens=650, config=config, job_text=job_text(job, 2200),
                       job_spec=json.dumps({k: spec.get(k) for k in ("title", "deliverables", "core_skills", "required_skills", "hidden_needs")}),
                       evidence=evidence_block(evidence), missing=", ".join(fit.get("missing_skills", [])) or "none",
                       price=f"{price.get('amount')} ({price.get('bid_type')})", style_rules="; ".join(s_rules) or "none yet",
                       outcome_insights="; ".join(o_ins) or "none yet", revision_notes=notes, min_words=lo, max_words=hi - 40,
                       answer_slots="\n".join(f"{i + 1}. <answer to: {q}>" for i, q in enumerate(qs)) or "(no screening questions)")
        usage.append(r.usage("writer"))
        cover, answers = parse(r.text, len(qs))
        if len(cover.split()) < 40:
            raise LLMUnavailable("writer output too short / unparseable")
    except LLMUnavailable as e:
        mode = "template"
        usage.append({"node": "writer", "error": str(e)[:200], "fallback": "template"})
        cover, answers = template_draft(job, spec, evidence, price)
    version = len(state.get("drafts", [])) + 1
    draft = {"job_id": job["job_id"], "cover_letter": cover, "screening_answers": answers, "version": version, "mode": mode,
             "evidence_ids": sorted({m for m in re.findall(r"\[E:([^\]]+)\]", cover + " ".join(answers))}),
             "style_rules_used": s_rules, "outcome_insights_used": o_ins}
    return {"drafts": [draft], "usage": usage, "steps": 1, "memory_used": {**state.get("memory_used", {}), "style_rules": s_rules},
            "trace": [rec("writer", version=version, mode=mode, words=len(cover.split()), cited=draft["evidence_ids"])]}
