"""Risk Assessor: client quality from history + scam / free-work / off-platform / injected-instruction flags.

Marketplace (read) via MCP: get_client_history. Lexicon + client-history model by default; optional small LLM.
"""
from __future__ import annotations

import re
from typing import Any

from agent.handoffs import RiskReport
from agent.nodes._util import injection_spans, job_text, rec, toolbox, trace_id
from common import config as cfg
from common.llm import LLMUnavailable, chat, parse_json

LEXICON = {
    "off_platform": r"\b(telegram|whatsapp|skype|wechat|signal|discord)\b|message me directly|contact (me )?(outside|directly)|"
                    r"(email|text) me at|we do not check messages here",
    "unpaid_work": r"free (test|trial|sample)|unpaid|complete the (full|entire) .{0,60}(free|before hiring)|best free submission|"
                   r"for free as a test|no pay(ment)? until",
    "upfront_fee": r"(pay|send) (a |an )?\$?\d+.{0,30}(fee|deposit)|onboarding fee|licen[cs]e fee|registration fee|training fee",
    "off_platform_payment": r"\b(crypto|usdt|bitcoin|gift ?cards?|western union|outside the platform|avoid (the )?fees)\b",
    "credentials": r"bank (login|details|account)|photo of your (id|card)|social security|send (us )?your (password|card)",
    "too_good": r"\$\s?\d{3,5}\s?/?\s?(per )?week|earn \$?\d{3,}.{0,20}(immediately|per week|weekly)|no experience (required|needed)",
}
_LEX = {k: re.compile(v, re.I) for k, v in LEXICON.items()}
WEIGHTS = {"off_platform": 0.55, "unpaid_work": 0.5, "upfront_fee": 0.7, "off_platform_payment": 0.6, "credentials": 0.8, "too_good": 0.5}


def client_quality(c: dict[str, Any]) -> float:
    q = 0.25
    q += 0.25 if c.get("payment_verified") else 0.0
    spent = float(c.get("total_spent_usd") or 0)
    q += 0.2 if spent >= 10000 else 0.12 if spent >= 1000 else 0.05 if spent > 0 else 0.0
    if c.get("rating"):
        q += 0.15 * max(0.0, (float(c["rating"]) - 3.0) / 2.0)
    q += min(0.15, 0.015 * int(c.get("reviews_count") or 0))
    return round(min(1.0, q), 3)


def assess(job: dict[str, Any], client: dict[str, Any]) -> RiskReport:
    text = f"{job.get('title', '')} {job.get('description', '')}"
    flags = [k for k, p in _LEX.items() if p.search(text)]
    inj = injection_spans(text)
    cq = client_quality(client or job.get("client_summary") or {})
    scam = 1.0
    for f in flags:
        scam *= 1 - WEIGHTS[f]
    scam = 1 - scam
    if not (client or {}).get("payment_verified") and float((client or {}).get("total_spent_usd") or 0) == 0:
        scam = 1 - (1 - scam) * 0.85  # brand-new unverified client raises the prior
    score = min(1.0, 0.75 * scam + 0.25 * (1 - cq))
    if inj:
        flags.append("prompt_injection")
    expl = (f"flags={flags or 'none'}; client quality {cq:.2f} (verified={bool((client or {}).get('payment_verified'))}, "
            f"spent=${float((client or {}).get('total_spent_usd') or 0):,.0f}, reviews={(client or {}).get('reviews_count', 0)})")
    if inj:
        expl += "; injected instructions detected and will be ignored"
    return RiskReport(score=round(score, 3), scam_likelihood=round(scam, 3), client_quality=cq, flags=flags,
                      injection_detected=bool(inj), injection_spans=[s[:200] for s in inj[:3]], explanation=expl)


async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    job = state["job"]
    tid = trace_id(state, config)
    client = {}
    trace = []
    if job.get("client_id"):
        client = await toolbox(config).call("risk_assessor", "get_client_history", {"client_id": job["client_id"]}, tid)
        trace.append(rec("risk_assessor", tool="get_client_history", client_id=job["client_id"]))
    report = assess(job, client)
    usage = []
    if cfg.get("models.use_llm.risk_assessor", False) and 0.15 < report.scam_likelihood < 0.6:
        try:
            r = await chat("risk_assessor", "risk_assessor", json_mode=True, max_tokens=150, config=config,
                           job_text=job_text(job, 1800), client=client)
            usage.append(r.usage("risk_assessor"))
            d = parse_json(r.text)
            p = float(d.get("scam_probability", report.scam_likelihood))
            report.scam_likelihood = round((report.scam_likelihood + p) / 2, 3)
            report.score = round(min(1.0, 0.75 * report.scam_likelihood + 0.25 * (1 - report.client_quality)), 3)
            report.explanation += f"; LLM: {d.get('reason', '')[:120]}"
        except (LLMUnavailable, ValueError) as e:
            usage.append({"node": "risk_assessor", "error": str(e)[:200]})
    trace.append(rec("risk_assessor", score=report.score, flags=report.flags))
    return {"risk_report": report.model_dump(), "analyses": {"risk": "done"}, "usage": usage, "steps": 1, "trace": trace}
