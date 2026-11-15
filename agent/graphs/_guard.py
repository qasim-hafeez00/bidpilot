"""Node guard: budgets (C4), per-node retries + timeouts, degraded mode and dead-letter (C7)."""
from __future__ import annotations

import asyncio
import inspect
import traceback
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt
from langgraph.store.base import BaseStore

from agent.marketplace_port import MarketplaceError, MarketplaceUnavailable
from common import config as cfg

HALTED = {"needs_attention", "dead_letter", "queued_degraded", "blocked", "rejected", "skipped", "watch"}
NODE_TIMEOUT = {"writer": 600, "critic": 300, "client_liaison": 300, "fit_matcher": 240, "verifier": 180}
NODE_ATTEMPTS = {"writer": 2, "critic": 2}


def halted(state: dict[str, Any]) -> bool:
    return state.get("status") in HALTED


def tokens_used(state: dict[str, Any]) -> int:
    return sum(int(u.get("in", 0)) + int(u.get("out", 0)) for u in state.get("usage", []) if not u.get("cached"))


def guard(name: str, fn):
    takes_store = "store" in inspect.signature(fn).parameters

    async def node(state: dict[str, Any], config: RunnableConfig, *, store: BaseStore | None = None) -> dict[str, Any]:
        b = cfg.get("budgets", {})
        if state.get("steps", 0) >= b.get("max_graph_steps", 30):
            return {"status": "needs_attention", "attention_reason": f"step budget exceeded at {name} ({state.get('steps')} steps)"}
        if tokens_used(state) > b.get("max_tokens_per_job", 16000):
            return {"status": "needs_attention", "attention_reason": f"token budget exceeded at {name} ({tokens_used(state)} tokens)"}
        attempts = NODE_ATTEMPTS.get(name, 3)
        delay = 1.0
        last = ""
        for i in range(attempts):
            try:
                call = fn(state, config, store=store) if takes_store else fn(state, config)
                return await asyncio.wait_for(call, timeout=NODE_TIMEOUT.get(name, 120))
            except GraphInterrupt:
                raise
            except MarketplaceUnavailable as e:
                return {"status": "queued_degraded", "attention_reason": f"marketplace unavailable during {name}: {str(e)[:200]}",
                        "errors": [f"{name}: {e}"[:300]], "steps": 1}
            except (MarketplaceError, PermissionError) as e:
                return {"status": "needs_attention", "attention_reason": f"{name}: {str(e)[:300]}", "errors": [f"{name}: {e}"[:300]], "steps": 1}
            except Exception as e:  # transient -> retry with backoff
                last = f"{type(e).__name__}: {e}"
                tb = traceback.format_exc(limit=3)
                if i < attempts - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
        return {"status": "dead_letter", "attention_reason": f"{name} failed after {attempts} attempts: {last[:200]}",
                "errors": [f"{name}: {last}\n{tb}"[:1500]], "steps": 1}

    node.__name__ = name
    return node
