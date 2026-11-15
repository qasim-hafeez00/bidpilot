"""Independent unsupported-claim checker used ONLY for evaluation (never by the system).

It knows the persona's ground-truth fact base (data/personas/<p>/facts.json): every skill (explicit + implied),
industry, project title, result number and years of experience. A first-person experience claim is
*unsupported* when it asserts a skill, number, industry or tenure that is not in the fact base, or claims
results with no number/skill/project at all but uses superlatives ("hundreds of projects", "expert in everything").
This is deliberately stricter and different from rag/verify.py, so the system is not graded by itself.
"""
from __future__ import annotations

import re
from typing import Any

from common.skills import extract_skills
from rag.verify import EXPERIENCE, FUTURE, SENT, strip_markers

NUM = re.compile(r"\d+(?:[.,]\d+)?")
VAGUE = re.compile(r"\b(hundreds of|many (similar )?projects|countless|dozens of|top[- ]rated|expert in (all|every)|"
                   r"world[- ]class|best in the)\b", re.I)
INDUSTRY_CLAIM = re.compile(r"\bfor (?:a|an|the|several|multiple)?\s*([a-z][a-z\- ]{2,25}?) (?:client|company|startup|firm|brand)s?\b", re.I)


def check(text: str, facts: dict[str, Any], job_text: str = "") -> dict[str, Any]:
    skills = {s.lower() for s in facts["skills"]}
    nums = set()
    for n in facts["numbers"] + [str(facts["years_experience"])]:
        nums.add(n.replace(",", "").rstrip("."))
    for p in facts["projects"]:
        for n in NUM.findall(p["result"] + " " + p["approach"] + " " + p["title"] + " " + p["date"]):
            nums.add(n.replace(",", ""))
    job_nums = {n.replace(",", "") for n in NUM.findall(job_text)}
    industries = {i.lower() for i in facts["industries"]}
    claims, unsupported = 0, []
    for s in SENT.split(strip_markers(text)):
        s = s.strip()
        if not s or s.endswith("?") or FUTURE.search(s) or not EXPERIENCE.search(s):
            continue
        claims += 1
        why = []
        bad_sk = [k for k in extract_skills(s) if k.lower() not in skills]
        if bad_sk:
            why.append(f"skills not in portfolio: {bad_sk}")
        bad_n = [n for n in NUM.findall(s) if n.replace(",", "") not in nums and n.replace(",", "") not in job_nums
                 and not re.fullmatch(r"20\d\d", n)]
        if bad_n:
            why.append(f"numbers not in portfolio: {bad_n}")
        m = re.search(r"(\d+)\+?\s*years", s, re.I)
        if m and int(m.group(1)) > facts["years_experience"]:
            why.append(f"overstated tenure: {m.group(0)}")
        for im in INDUSTRY_CLAIM.finditer(s):
            ind = im.group(1).strip().lower()
            if not any(ind in i or i in ind for i in industries) and len(ind.split()) <= 2 and ind not in {"similar", "previous", "past", "large", "small", "few"}:
                why.append(f"industry not in portfolio: {ind}")
        if VAGUE.search(s):
            why.append("unverifiable superlative")
        if why:
            unsupported.append({"sentence": s, "why": why})
    return {"claims": claims, "unsupported": len(unsupported), "details": unsupported}
