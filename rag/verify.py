"""Claim verification (B3): split a draft into claims and ground each against retrieved evidence.

A *claim* is a first-person statement of experience or a factual result (numbers, skills, clients).
Forward-looking statements ("I would...", questions, greetings) are not claims.
Each claim -> supported | partly_supported | unsupported using
  (1) a cross-encoder relevance score between claim and evidence chunk, and
  (2) entity checks: every skill and every number in the claim must appear in the evidence.
Unsupported claims are removed before the Critic sees the draft.
"""
from __future__ import annotations

import re
from typing import Any

from common import config as cfg
from common.skills import extract_skills

MARK = re.compile(r"\s*(?:\[|【)E:([^\]】]+)(?:\]|】)")
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")
FUTURE = re.compile(r"^\s*(i would|i will|i'd|i can|i could|i propose|i plan|i'll|let's|we can|we could|happy to|"
                    r"would you|could you|do you|is the|are you|thanks|thank you|best|regards|cheers|looking forward)", re.I)
EXPERIENCE = re.compile(r"\b(i|i've|i have|my|we|our|me)\b.*\b(built|build|delivered|led|developed|created|designed|shipped|"
                        r"implemented|cut|reduced|improved|increased|raised|worked|deployed|trained|fine-tuned|migrated|"
                        r"automated|launched|years?|experience|experienced|expert|speciali[sz]e|handled|saved|achieved)\b", re.I)
NUM = re.compile(r"\d+(?:[.,]\d+)?")


def strip_markers(text: str) -> str:
    return MARK.sub("", text)


def cited(text: str) -> list[str]:
    return [c.strip() for m in MARK.finditer(text) for c in m.group(1).split(",")]


def split_claims(draft: str) -> list[dict[str, Any]]:
    out = []
    for i, s in enumerate(x for x in SENT.split(draft.strip()) if x.strip()):
        plain = strip_markers(s).strip()
        is_claim = bool(plain) and not plain.endswith("?") and not FUTURE.search(plain) and (
            bool(EXPERIENCE.search(plain)) or bool(NUM.search(plain)) or bool(cited(s)))
        out.append({"idx": i, "sentence": s, "text": plain, "is_claim": is_claim, "cited": cited(s)})
    return out


def _ev_text(e: dict[str, Any]) -> str:
    return f"{e.get('title', '')}. {e.get('text', '')} Skills: {', '.join(e.get('skills') or [])}"


def verify_claims(draft: str, evidence: list[dict], scorer=None) -> list[dict]:
    """Label every claim. `evidence` items need: evidence_id, project_id (optional), title, text, skills."""
    from rag.index.models import rerank

    scorer = scorer or rerank
    hi, lo = cfg.get("thresholds.verify_support", 0.30), cfg.get("thresholds.verify_partial", 0.08)
    results = []
    for c in split_claims(draft):
        if not c["is_claim"]:
            results.append({**c, "label": "not_a_claim"})
            continue
        pool = [e for e in evidence if e.get("evidence_id") in c["cited"] or e.get("project_id") in c["cited"]] or evidence
        if not pool:
            results.append({**c, "label": "unsupported", "score": 0.0, "evidence_id": None, "missing": ["no evidence"]})
            continue
        texts = [_ev_text(e) for e in pool]
        scores = scorer(c["text"], texts)
        best = int(max(range(len(pool)), key=lambda i: scores[i]))
        joined = " ".join(texts).lower()
        missing = [s for s in extract_skills(c["text"]) if s.lower() not in joined
                   and not any(s in (e.get("skills") or []) for e in pool)]
        nums = [n for n in NUM.findall(c["text"]) if n not in joined and n.replace(",", "") not in joined]
        score = float(scores[best])
        if score >= hi and not missing and not nums:
            label = "supported"
        elif (score >= lo and len(missing) <= 1 and not nums) or (score >= hi and (missing or nums) and len(missing) + len(nums) <= 1):
            label = "partly_supported"
        else:
            label = "unsupported"
        results.append({**c, "label": label, "score": round(score, 4), "evidence_id": pool[best].get("evidence_id"),
                        "project_id": pool[best].get("project_id"), "missing": missing + nums})
    return results


def apply(draft: str, results: list[dict]) -> tuple[str, list[dict]]:
    """Remove unsupported claims; return (clean draft with markers, removed claims)."""
    keep, removed = [], []
    for r in results:
        if r["label"] == "unsupported":
            removed.append(r)
        else:
            keep.append(r["sentence"])
    return " ".join(keep).strip(), removed


def stats(results: list[dict]) -> dict[str, Any]:
    claims = [r for r in results if r["label"] != "not_a_claim"]
    n = len(claims)
    c = {k: sum(r["label"] == k for r in claims) for k in ("supported", "partly_supported", "unsupported")}
    return {"claims": n, **c, "supported_ratio": round(c["supported"] / n, 3) if n else 1.0}
