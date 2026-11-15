"""Job Analyst: extract a structured JobSpec (deliverables, skills, budget, timeline, screening questions, hidden needs).

Rules first (deterministic, fast); optional small-LLM enrichment for deliverables / hidden needs (config models.use_llm.analyst).
No MCP access (it only reads the job already in state).
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from agent.handoffs import JobSpec
from agent.nodes._util import job_text, rec, strip_injections
from common import config as cfg
from common.llm import LLMUnavailable, chat, parse_json
from common.skills import extract_skills, skill_domain
from rag.requirements import REQ_CUE, sentences


def rules_spec(job: dict[str, Any]) -> JobSpec:
    desc = strip_injections(job.get("description", ""))
    skills = list(dict.fromkeys((job.get("skills") or []) + extract_skills(f"{job.get('title', '')}. {desc}")))[:10]
    core = [s for s in extract_skills(job.get("title", "")) if s in skills] or skills[:2]
    dom = Counter(skill_domain(s) for s in skills).most_common(1)[0][0] if skills else "other"
    deliverables = [s[:160] for s in sentences(desc) if REQ_CUE.search(s)][:5]
    hourly = bool(job.get("is_hourly"))
    return JobSpec(job_id=job["job_id"], title=job.get("title", ""), deliverables=deliverables, required_skills=skills,
                   core_skills=core, budget_type="hourly" if hourly else "fixed",
                   budget_min=job.get("hourly_low") if hourly else job.get("budget"),
                   budget_max=job.get("hourly_high") if hourly else job.get("budget"),
                   timeline=job.get("duration"), experience_level=job.get("experience_level"),
                   screening_questions=list(job.get("screening_questions") or []), domain=dom)


async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    job = state["job"]
    spec = rules_spec(job)
    usage = []
    if cfg.get("models.use_llm.analyst", False):
        try:
            r = await chat("analyst", "analyst", json_mode=True, max_tokens=300, config=config, job_text=job_text(job, 2000),
                           skills=spec.required_skills, budget=f"{spec.budget_min}-{spec.budget_max} {spec.budget_type}",
                           timeline=spec.timeline)
            usage.append(r.usage("analyst"))
            d = parse_json(r.text)
            spec.deliverables = [str(x)[:160] for x in d.get("deliverables", [])][:5] or spec.deliverables
            spec.hidden_needs = [str(x)[:160] for x in d.get("hidden_needs", [])][:3]
            spec.extraction = "rules+llm"
        except LLMUnavailable as e:
            usage.append({"node": "analyst", "error": str(e)[:200]})
    return {"job_spec": spec.model_dump(), "analyses": {"analyst": "done"}, "usage": usage, "steps": 1,
            "trace": [rec("analyst", skills=spec.required_skills, core=spec.core_skills, extraction=spec.extraction)]}
