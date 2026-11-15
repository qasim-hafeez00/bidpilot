"""Pricing Strategist: bid from market statistics (Marketplace MCP), the client's posted budget and the user's floor;
decide whether the Connects cost is worth it (expected value vs Connects price)."""
from __future__ import annotations

from typing import Any

from agent.handoffs import PriceQuote
from agent.nodes._util import rec, toolbox, trace_id
from common import config as cfg


def quote(job: dict[str, Any], stats: dict[str, Any], settings: dict[str, Any], fit: float, p_reply_prior: float = 0.15) -> PriceQuote:
    hourly = bool(job.get("is_hourly"))
    floor = float(settings.get("hourly_floor" if hourly else "min_fixed", 0))
    if hourly:
        lo, hi = job.get("hourly_low"), job.get("hourly_high")
        market = float(stats.get("p60", 30))
        band_lo = max(float(stats.get("p40", market * 0.8)), (lo or 0) * 0.9)
        band_hi = min(max(float(stats.get("p75", market * 1.2)), lo or 0), (hi or 1e9) * 1.15) if (lo or hi) else float(stats.get("p75", market * 1.2))
        if band_lo > band_hi:
            band_lo, band_hi = (lo or band_hi) * 0.9, (hi or band_lo) * 1.15
        target = market if not (lo or hi) else min(max(market, lo or 0), hi or market)
        amount = max(floor, target)
        why = (f"market p60 ${market}/h for this domain (n={stats.get('n')}); client range ${lo}-${hi}/h; "
               f"your floor ${floor}/h -> ${amount:.0f}/h")
        value = amount * 20
    else:
        b = float(job.get("budget") or 0)
        band_lo, band_hi = b * 0.85, b * 1.15
        amount = max(floor, b) if b else max(floor, float(stats.get("p50", 300)))
        why = f"client budget ${b:,.0f}; market median ${stats.get('p50')} (n={stats.get('n')}); your minimum ${floor:,.0f} -> ${amount:,.0f}"
        value = amount
    cost = int(job.get("connects_cost") or 0)
    usd = cost * float(cfg.get("marketplace.connects_usd", 0.15))
    ev = p_reply_prior * (0.5 + fit) * 0.35 * value * 0.1  # P(reply) x P(hire|reply) x value x margin-proxy
    worth = ev >= usd * 3
    why += f". Connects {cost} (${usd:.2f}) vs expected value ${ev:.2f} -> {'worth it' if worth else 'not worth it'}"
    return PriceQuote(amount=round(amount, 2), bid_type="hourly" if hourly else "fixed",
                      band=(round(band_lo, 2), round(band_hi, 2)), rationale=why, connects_cost=cost, connects_usd=round(usd, 2),
                      expected_value_usd=round(ev, 2), connects_worth_it=worth)


async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    job, spec = state["job"], state.get("job_spec", {})
    kind = "hourly" if job.get("is_hourly") else "fixed"
    stats = await toolbox(config).call("pricing", "get_market_stats", {"domain": spec.get("domain", "other"), "kind": kind},
                                       trace_id(state, config))
    prior = float(state.get("memory_used", {}).get("reply_rate_prior", 0.15))
    q = quote(job, stats, state.get("settings", {}), float(state.get("fit_report", {}).get("score", 0.5)), prior)
    return {"price_quote": q.model_dump(), "steps": 1,
            "trace": [rec("pricing", tool="get_market_stats", amount=q.amount, band=q.band, connects=q.connects_cost)]}
