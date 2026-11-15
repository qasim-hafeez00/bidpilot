"""Decision node (join of the three parallel branches): skip | watch | bid, with reasons. Thresholds from config."""
from __future__ import annotations

from typing import Any

from agent.handoffs import BidDecision
from agent.nodes._util import rec
from common import config as cfg


def decide(job: dict[str, Any], fit: dict[str, Any], risk: dict[str, Any], settings: dict[str, Any]) -> BidDecision:
    min_fit, watch_fit = cfg.get("thresholds.minimum_fit_score", 0.55), cfg.get("thresholds.watch_fit_score", 0.40)
    max_risk = cfg.get("thresholds.maximum_risk_score", 0.60)
    reasons: list[str] = []
    f, r = float(fit.get("score", 0)), float(risk.get("score", 0))
    if r > max_risk or risk.get("scam_likelihood", 0) >= 0.5:
        reasons.append(f"risk {r:.2f} > {max_risk} or scam likelihood {risk.get('scam_likelihood', 0):.2f} (flags: {risk.get('flags')})")
        return BidDecision(action="skip", reasons=reasons, auto=False)
    floor_h, floor_f = float(settings.get("hourly_floor", 0)), float(settings.get("min_fixed", 0))
    if job.get("is_hourly"):
        top = job.get("hourly_high") or job.get("hourly_low")
        price_ok = top is None or float(top) >= floor_h
        if not price_ok:
            reasons.append(f"client's max rate ${top}/h is below your floor ${floor_h}/h")
    else:
        price_ok = float(job.get("budget") or 0) >= floor_f
        if not price_ok:
            reasons.append(f"budget ${job.get('budget')} is below your minimum ${floor_f}")
    left = int(settings.get("weekly_connects_budget", 10**6)) - int(settings.get("connects_spent_this_week", 0))
    cost = int(job.get("connects_cost") or 0)
    connects_ok = cost <= left
    if not connects_ok:
        reasons.append(f"Connects cost {cost} exceeds the {left} left in this week's budget")
    reasons += fit.get("reasons", [])
    if risk.get("injection_detected"):
        reasons.append("post contains injected instructions - they are ignored")
    if not price_ok:  # below the user's floor: never worth Connects, whatever the fit
        return BidDecision(action="skip", reasons=reasons, auto=settings.get("autonomy") == "auto_skip_low_fit")
    if f >= min_fit and connects_ok:
        return BidDecision(action="bid", reasons=[f"fit {f:.2f} >= {min_fit}"] + reasons)
    if f >= watch_fit:
        return BidDecision(action="watch", reasons=[f"fit {f:.2f} borderline (watch >= {watch_fit})"] + reasons)
    auto = settings.get("autonomy") == "auto_skip_low_fit" and f < watch_fit
    return BidDecision(action="skip", reasons=[f"fit {f:.2f} < {watch_fit}"] + reasons, auto=auto)


async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    if state.get("status") in ("queued_degraded", "dead_letter", "needs_attention"):
        return {"steps": 1, "trace": [rec("decide", action="halted", status=state.get("status"))]}
    d = decide(state["job"], state.get("fit_report", {}), state.get("risk_report", {}), state.get("settings", {}))
    if state.get("settings", {}).get("force_bid") and d.action != "bid" and state.get("risk_report", {}).get("scam_likelihood", 0) < 0.5:
        d = BidDecision(action="bid", reasons=["user chose to bid anyway"] + d.reasons)
    status = {"skip": "skipped", "watch": "watch", "bid": "running"}[d.action]
    return {"decision": d.model_dump(), "status": status, "steps": 1, "trace": [rec("decide", action=d.action, reasons=d.reasons[:4])]}
