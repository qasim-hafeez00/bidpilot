"""Deterministic requirement decomposition (used by V1, the Fit Matcher and the Job Analyst)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from common.skills import SKILLS, extract_skills

REQ_CUE = re.compile(r"\b(need|must|should|require|looking for|experience (with|in)|build|develop|create|implement|"
                     r"integrat\w*|deploy|design|migrat\w*|automat\w*|analy[sz]e|dashboard|model|pipeline)\b", re.I)
SENT = re.compile(r"(?<=[.!?;:])\s+|\s+[-*•]\s+|\n+")


@dataclass
class Requirement:
    text: str
    skill: str | None = None
    core: bool = False

    @property
    def query(self) -> str:
        if self.skill:
            aliases = [a for a in SKILLS.get(self.skill, [])[:3] if a.lower() != self.skill.lower()]
            return f"{self.skill} ({', '.join(aliases)}): {self.text}" if aliases else f"{self.skill}: {self.text}"
        return self.text


def sentences(text: str) -> list[str]:
    return [s.strip(" -*•") for s in SENT.split(text) if len(s.strip()) > 25]


def decompose(title: str, description: str, max_req: int = 8) -> list[Requirement]:
    sents = sentences(description)
    title_skills = set(extract_skills(title))
    reqs: list[Requirement] = []
    for sk in extract_skills(f"{title}. {description}"):
        ctx = next((s for s in sents if sk.lower() in s.lower()
                    or any(a in s.lower() for a in SKILLS.get(sk, []))), title)
        reqs.append(Requirement(ctx[:240], sk, sk in title_skills))
    for s in sents:
        if len(reqs) >= max_req:
            break
        if REQ_CUE.search(s) and not extract_skills(s):
            reqs.append(Requirement(s[:240], None, False))
    reqs.sort(key=lambda r: (not r.core, r.skill is None))
    return reqs[:max_req] or [Requirement(title, None, True)]
