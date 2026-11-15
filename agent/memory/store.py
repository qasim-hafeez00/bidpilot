"""Long-term memory on a LangGraph BaseStore (PostgresStore in production, InMemoryStore in tests).

Namespaces (per user = tenant):
  ("style", user)              promoted style rules           <- only via promotion_rules.should_promote_style
  ("style_edits", user)        last N edit PATTERN lists       (names only, never the user's text)
  ("outcome", user)            per-category counts by opening style
  ("outcome_insights", user)   promoted insights               <- only via promotion_rules.outcome_insight
"""
from __future__ import annotations

import time
from typing import Any

from agent.memory import promotion_rules as pr


async def style_rules(store, user: str) -> list[str]:
    if store is None:
        return []
    items = await store.asearch(("style", user), limit=50)
    return [i.value["rule"] for i in items]


async def record_edit(store, user: str, original: str, edited: str) -> dict[str, Any]:
    """Diff -> patterns -> promote/demote by rule. Returns what changed (for the trace and the UI)."""
    pats = pr.edit_patterns(original, edited)
    hist_item = await store.aget(("style_edits", user), "history")
    hist: list[list[str]] = (hist_item.value["edits"] if hist_item else []) + [pats]
    hist = hist[-pr.WINDOW * 2:]
    await store.aput(("style_edits", user), "history", {"edits": hist, "updated": time.time()})
    promoted, demoted = [], []
    for p in {x for pats_ in hist[-pr.WINDOW:] for x in pats_}:
        if pr.should_promote_style(p, hist) and not await store.aget(("style", user), p):
            await store.aput(("style", user), p, {"rule": pr.rule_text(p), "pattern": p, "promoted_at": time.time(),
                                                  "support": f"{sum(p in h for h in hist[-pr.WINDOW:])}/{pr.WINDOW} recent edits"})
            promoted.append(p)
    for it in await store.asearch(("style", user), limit=50):
        if pr.should_demote_style(it.key, hist):
            await store.adelete(("style", user), it.key)
            demoted.append(it.key)
    return {"patterns": pats, "promoted": promoted, "demoted": demoted}


async def outcome_insights(store, user: str, category: str) -> list[str]:
    if store is None:
        return []
    it = await store.aget(("outcome_insights", user), category)
    return [it.value["insight"]] if it else []


async def reply_rate_prior(store, user: str, category: str) -> float:
    if store is None:
        return 0.15
    it = await store.aget(("outcome", user), category)
    if not it:
        return 0.15
    sub = sum(a["submitted"] for a in it.value["arms"].values())
    rep = sum(a["replied"] for a in it.value["arms"].values())
    return (rep + 1.5) / (sub + 10)  # smoothed towards a 15% prior


async def record_outcome(store, user: str, category: str, style: str, replied: bool, hired: bool = False) -> str | None:
    it = await store.aget(("outcome", user), category)
    arms = it.value["arms"] if it else {}
    a = arms.setdefault(style, {"submitted": 0, "replied": 0, "hired": 0})
    a["submitted"] += 1
    a["replied"] += int(replied)
    a["hired"] += int(hired)
    await store.aput(("outcome", user), category, {"arms": arms, "updated": time.time()})
    insight = pr.outcome_insight(category, arms)
    if insight:
        await store.aput(("outcome_insights", user), category, {"insight": insight, "promoted_at": time.time()})
    return insight


async def list_memory(store, user: str) -> list[dict[str, Any]]:
    out = []
    for ns in ("style", "outcome_insights"):
        for it in await store.asearch((ns, user), limit=100):
            out.append({"namespace": ns, "key": it.key, **it.value})
    return out


async def delete_memory(store, user: str, namespace: str, key: str) -> None:
    if namespace not in ("style", "outcome_insights"):
        raise ValueError("only promoted memory can be deleted from the UI")
    await store.adelete((namespace, user), key)
