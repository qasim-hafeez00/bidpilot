"""Proposal-level evaluation: for a fixed set of gold-bid dev jobs, run the full bid graph (LLM writer), let the harness
approve at the interrupt (it plays the human), submit to an isolated GigSim, tick the simulated clients, and record:
unsupported claims before/after verification (independent fact checker), critic loops, compliance hits, latency, tokens,
USD, reply/interview rate. Also writes the proposals for the judge and for human labelling.

    python -m evals.runners.gigsim_outcomes --configs best,v0 --per-persona 6
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agent.graphs.bid_graph import build_bid_graph
from agent.mcp_client import InMemoryToolBox
from common import config as cfg
from common.tracing import new_trace_id, run_config
from evals.checkers.fact_check import check
from evals.runners.common import PERSONAS, RESULTS, ROOT, facts, load_jobs, mean, pct, write
from evals.runners.eval_env import eval_gigsim, outcomes, tick
from rag.verify import strip_markers


def pick_jobs(persona: str, n: int, split: str = "dev") -> list[dict]:
    jobs = [j for j in load_jobs(persona, split) if j["gold"]["gold_decision"] == "bid"]
    random.Random(4016).shuffle(jobs)
    return jobs[:n]


async def run_config_set(name: str, variant: str, strategy: str | None, per_persona: int, base_split: str = "dev") -> list[dict]:
    os.environ["RAG_VARIANT"] = variant
    cfg.reload()
    rows = []
    for persona in PERSONAS:
        prof = json.loads((ROOT / "data" / "personas" / persona / "profile.json").read_text())
        settings = {"hourly_floor": prof["hourly_floor"], "min_fixed": prof["min_fixed"], "weekly_connects_budget": 10**6,
                    "force_bid": True, "proposal_strategy": strategy}
        acct = f"fl-{name}-{persona}"
        async with InMemoryToolBox(f"eval-{name}", persona, f"tok-{acct}") as tb:
            g = build_bid_graph(MemorySaver(), InMemoryStore())
            for j in pick_jobs(persona, per_persona, base_split):
                tid = new_trace_id()
                rc = run_config(f"{name}:{j['job_id']}", tid, f"eval-{name}", toolbox=tb)
                public = {k: v for k, v in j.items() if k not in ("gold", "persona_id", "scam_type", "injected")}
                t0 = time.perf_counter()
                st = await g.ainvoke({"job_id": j["job_id"], "job": public, "user_id": f"eval-{name}", "persona": persona,
                                      "settings": settings, "trace_id": tid}, rc)
                dt = time.perf_counter() - t0
                if st.get("status") == "awaiting_approval":
                    st = await g.ainvoke(Command(resume={"action": "approve", "approver": "eval-harness"}), rc)
                drafts = st.get("drafts", [])
                raw = drafts[0]["cover_letter"] if drafts else ""
                final = drafts[-1]["cover_letter"] if drafts else ""
                f = facts(persona)
                usage = [u for u in st.get("usage", []) if isinstance(u, dict)]
                rows.append({
                    "config": name, "variant": variant, "strategy": strategy, "persona": persona, "job_id": j["job_id"],
                    "title": j["title"], "status": st.get("status"), "proposal_id": (st.get("submission") or {}).get("proposal_id"),
                    "raw_draft": strip_markers(raw), "final_draft": strip_markers(final), "final_with_markers": final,
                    "writer_mode": drafts[0].get("mode") if drafts else None,
                    "unsupported_before": check(raw, f, j["description"])["unsupported"],
                    "unsupported_after": check(final, f, j["description"])["unsupported"],
                    "claims_before": check(raw, f, j["description"])["claims"],
                    "verifier_removed": len((st.get("verification") or {}).get("removed", [])),
                    "critic_loops": st.get("revisions", 0),
                    "compliance_hits": len((st.get("compliance_verdict") or {}).get("violations", [])),
                    "latency_s": round(dt, 2), "tokens": sum(int(u.get("in", 0)) + int(u.get("out", 0)) for u in usage),
                    "usd": round(sum(float(u.get("usd", 0)) for u in usage), 6),
                    "job_text": j["description"][:1500], "trace_id": tid,
                })
                print(f"  {name} {persona} {j['job_id']} {st.get('status')} {dt:.0f}s unsup {rows[-1]['unsupported_before']}->{rows[-1]['unsupported_after']}", flush=True)
    return rows


def summarize(rows: list[dict]) -> dict:
    sub = [r for r in rows if r.get("reply_status")]
    return {"n": len(rows), "submitted": len(sub),
            "unsupported_per_proposal_before": round(mean([r["unsupported_before"] for r in rows]), 3),
            "unsupported_per_proposal_after": round(mean([r["unsupported_after"] for r in rows]), 3),
            "verifier_removed_per_proposal": round(mean([r["verifier_removed"] for r in rows]), 3),
            "critic_loops_mean": round(mean([r["critic_loops"] for r in rows]), 3),
            "reply_rate": round(mean([float(r["reply_status"] in ("replied", "interview", "hired")) for r in sub]), 3) if sub else None,
            "p50_latency_s": round(pct([r["latency_s"] for r in rows], 50), 1), "p95_latency_s": round(pct([r["latency_s"] for r in rows], 95), 1),
            "tokens_per_proposal": round(mean([r["tokens"] for r in rows]), 1), "usd_per_proposal": round(mean([r["usd"] for r in rows]), 6),
            "template_fallback_rate": round(mean([float(r["writer_mode"] == "template") for r in rows]), 3)}


async def main_async(a) -> None:
    configs = [c.split(":") for c in a.configs.split(",")]  # name[:variant[:strategy]]
    specs = [(c[0], c[1] if len(c) > 1 else c[0], c[2] if len(c) > 2 else None) for c in configs]
    accounts = [f"fl-{n}-{p}" for n, _, _ in specs for p in PERSONAS]
    allrows = []
    with eval_gigsim(accounts, include_test=a.split == "test") as base:
        for name, variant, strategy in specs:
            rows = await run_config_set(name, variant, strategy, a.per_persona, a.split)
            tick(base)
            for p in PERSONAS:
                st = outcomes(base, f"fl-{name}-{p}")
                for r in rows:
                    if r["proposal_id"] in st:
                        r["reply_status"] = st[r["proposal_id"]]
            allrows += rows
    summary = {name: summarize([r for r in allrows if r["config"] == name]) for name, _, _ in specs}
    for k, v in summary.items():
        print(k, v)
    write(a.out, {"per_persona": a.per_persona, "split": a.split, "model_profile": cfg.get("models.profile"),
                  "client_mode": os.environ.get("GIGSIM_CLIENT_MODE", "rule"), "summary": summary})
    with open(RESULTS / a.out.replace(".json", "_rows.jsonl"), "w", encoding="utf-8") as fh:
        for r in allrows:
            fh.write(json.dumps(r) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="best,v0")
    ap.add_argument("--per-persona", type=int, default=6)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--out", default="proposals.json")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
