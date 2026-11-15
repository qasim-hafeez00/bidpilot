from __future__ import annotations

from fastapi import APIRouter

from apps.api.auth.security import CurrentUser
from common import db

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics")
async def analytics(user=CurrentUser):
    uid = user["id"]
    by_cat = await db.fetch(
        "SELECT COALESCE(category,'other') AS category, COUNT(*) AS submitted, "
        "SUM((stage IN ('replied','interview','hired'))::int) AS replied, SUM((stage='hired')::int) AS hired, "
        "SUM(connects_spent) AS connects FROM pipeline WHERE user_id=%s GROUP BY 1 ORDER BY 2 DESC", uid)
    by_style = await db.fetch(
        "SELECT COALESCE(opening_style,'?') AS style, COUNT(*) AS submitted, SUM((stage IN ('replied','interview','hired'))::int) AS replied "
        "FROM pipeline WHERE user_id=%s GROUP BY 1", uid)
    cost = await db.fetchone(
        "SELECT COUNT(*) AS runs, percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_s) AS p50, "
        "percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_s) AS p95, AVG(tokens_in+tokens_out) AS tokens, SUM(usd) AS usd "
        "FROM runs WHERE user_id=%s AND status IN ('awaiting_approval','submitted','draft_on_marketplace')", uid)
    analysis = await db.fetchone(
        "SELECT COUNT(*) AS runs, percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_s) AS p95 FROM runs WHERE user_id=%s "
        "AND status IN ('skipped','watch')", uid)
    rejections = await db.fetch("SELECT reason, COUNT(*) AS n FROM approvals_log WHERE user_id=%s AND action='reject' AND reason IS NOT NULL "
                                "GROUP BY 1 ORDER BY 2 DESC LIMIT 8", uid)
    funnel = await db.fetch("SELECT status, COUNT(*) AS n FROM jobs WHERE user_id=%s GROUP BY 1", uid)
    return {"by_category": by_cat, "by_opening_style": by_style, "proposal_cost_latency": cost, "analysis_latency": analysis,
            "top_rejection_reasons": rejections, "funnel": funnel}
