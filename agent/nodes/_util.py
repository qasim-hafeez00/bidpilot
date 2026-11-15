"""Helpers shared by nodes: tool access, untrusted-text handling, trace + usage records."""
from __future__ import annotations

import re
import time
from typing import Any

from common.pii import mask

INJECTION_PATTERNS = [
    r"ignore (all |any |your )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |any |your )?(prior|previous)? ?(policy|instructions|rules)",
    r"\b(note|instruction)s? (to|for) (ai|automated|llm|gpt|chatgpt) (assistants?|agents?|bots?|writers?)",
    r"if you are an? (ai|bot|language model|llm)",
    r"\[system\]|<\s*system\s*>|<!--.*?(ai|agent).*?-->",
    r"new instruction",
    r"(start|begin) (your|the) (reply|proposal|answer) with the word",
    r"reply with the word",
]
_INJ = re.compile("|".join(INJECTION_PATTERNS), re.I | re.S)


def toolbox(config: dict[str, Any]):
    tb = (config or {}).get("configurable", {}).get("toolbox")
    if tb is None:
        raise RuntimeError("no MCP toolbox in config['configurable']['toolbox']")
    return tb


def trace_id(state: dict[str, Any], config: dict[str, Any] | None = None) -> str | None:
    return state.get("trace_id") or ((config or {}).get("configurable", {}) or {}).get("trace_id")


def untrusted(text: str) -> str:
    """Mask PII and neutralise delimiter spoofing before untrusted text enters a prompt or a trace."""
    t = mask(text or "")
    return t.replace("<<<", "«").replace(">>>", "»").replace("JOB>>>", "JOB»")


def injection_spans(text: str) -> list[str]:
    spans = []
    for m in _INJ.finditer(text or ""):
        s = max(0, m.start() - 40)
        spans.append(text[s: m.end() + 80].strip())
    return spans


def strip_injections(text: str) -> str:
    """Remove sentences that carry injected instructions (defence in depth; the prompt also delimits the text)."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        if not _INJ.search(sent):
            out.append(sent)
    return " ".join(out)


def rec(node: str, **kw: Any) -> dict[str, Any]:
    return {"node": node, "ts": time.time(), **kw}


def job_text(job: dict[str, Any], limit: int = 2500) -> str:
    return untrusted(f"{job.get('title', '')}\n\n{job.get('description', '')}")[:limit]
