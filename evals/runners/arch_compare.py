"""R&D question C: one ReAct agent holding all (read) tools vs a prebuilt langgraph-supervisor vs the hand-built graph.
Same jobs, same model, same MCP tools (in-memory). Reports bid-or-skip accuracy, unsupported claims (independent fact
checker), compliance violations left in the output, tokens and latency.

    python -m evals.runners.arch_compare --per-persona 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import time

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from agent.graphs.bid_graph import build_bid_graph
from agent.mcp_client import InMemoryToolBox
from agent.nodes import compliance
from common.llm import chat_model, load_prompt, model_for
from common.tracing import new_trace_id, run_config
from evals.checkers.fact_check import check
from evals.runners.common import PERSONAS, ROOT, facts, load_jobs, mean, pct, write
from rag.verify import strip_markers

READ_TOOLS = {"get_job", "get_client_history", "search_evidence", "get_case_study", "get_market_stats"}


def pick(persona: str, n: int) -> list[dict]:
    js = load_jobs(persona)
    r = random.Random(11)
    bids = [j for j in js if j["gold"]["gold_decision"] == "bid"]
    scams = [j for j in js if j["gold"]["gold_scam"]]
    skips = [j for j in js if j["gold"]["gold_decision"] == "skip" and not j["gold"]["gold_scam"]]
    r.shuffle(bids), r.shuffle(scams), r.shuffle(skips)
    return (bids[: (n + 1) // 2] + scams[:1] + skips)[:n]


def parse_final(text: str) -> tuple[str, str]:
    dec = "bid" if re.search(r"DECISION:\s*BID", text, re.I) else "skip"
    m = re.search(r"PROPOSAL:\s*(.*)$", text, re.S | re.I)
    prop = (m.group(1).strip() if m else "") if dec == "bid" else ""
    return dec, "" if prop.upper().startswith("NONE") else prop


def usage_of(msgs) -> int:
    return sum((getattr(m, "usage_metadata", None) or {}).get("total_tokens", 0) for m in msgs)


async def run_react(tb, persona, job, prof):
    from langgraph.prebuilt import create_react_agent

    tools = [t for t in await tb.langchain_tools() if t.name in READ_TOOLS]
    prov, mdl = model_for("writer")
    agent = create_react_agent(chat_model(prov, mdl, max_tokens=600), tools,
                               prompt=load_prompt("react_agent").render(job_id=job["job_id"], floor=prof["hourly_floor"], min_fixed=prof["min_fixed"])[0])
    res = await agent.ainvoke({"messages": [("user", load_prompt("react_agent").render(job_id=job["job_id"], floor=prof["hourly_floor"],
                                                                                       min_fixed=prof["min_fixed"])[1])]}, {"recursion_limit": 16})
    return (*parse_final(res["messages"][-1].content), usage_of(res["messages"]))


async def run_supervisor(tb, persona, job, prof):
    from langgraph.prebuilt import create_react_agent
    from langgraph_supervisor import create_supervisor

    tools = {t.name: t for t in await tb.langchain_tools()}
    prov, mdl = model_for("writer")
    m = chat_model(prov, mdl, max_tokens=600)
    research = create_react_agent(m, [tools["get_job"], tools["get_client_history"], tools["get_market_stats"]], name="researcher",
                                  prompt="Fetch the job and client history; report facts, risks and the posted budget.")
    portfolio = create_react_agent(m, [tools["search_evidence"], tools["get_case_study"]], name="portfolio",
                                   prompt="Find portfolio evidence for each requirement; quote it exactly.")
    writer = create_react_agent(m, [], name="writer", prompt="Write the proposal only from evidence the portfolio agent quoted.")
    sys_prompt, user = load_prompt("react_agent").render(job_id=job["job_id"], floor=prof["hourly_floor"], min_fixed=prof["min_fixed"])
    sup = create_supervisor([research, portfolio, writer], model=m, prompt=sys_prompt).compile()
    res = await sup.ainvoke({"messages": [("user", user)]}, {"recursion_limit": 30})
    return (*parse_final(res["messages"][-1].content), usage_of(res["messages"]))


async def run_graph(tb, persona, job, prof):
    g = build_bid_graph(MemorySaver(), InMemoryStore())
    tid = new_trace_id()
    public = {k: v for k, v in job.items() if k not in ("gold", "persona_id", "scam_type", "injected")}
    st = await g.ainvoke({"job_id": job["job_id"], "job": public, "user_id": "arch", "persona": persona,
                          "settings": {"hourly_floor": prof["hourly_floor"], "min_fixed": prof["min_fixed"]}},
                         run_config(f"arch:{job['job_id']}", tid, "arch", toolbox=tb))
    dec = (st.get("decision") or {}).get("action", "skip")
    prop = strip_markers(st["drafts"][-1]["cover_letter"]) if st.get("drafts") else ""
    return ("bid" if dec == "bid" else "skip"), prop, sum(int(u.get("in", 0)) + int(u.get("out", 0)) for u in st.get("usage", []) if isinstance(u, dict))


async def main_async(a) -> None:
    archs = {"react_single_agent": run_react, "langgraph_supervisor": run_supervisor, "hand_built_graph": run_graph}
    rows = []
    for persona in PERSONAS:
        prof = json.loads((ROOT / "data" / "personas" / persona / "profile.json").read_text())
        async with InMemoryToolBox("arch", persona, f"dev-token-{persona}") as tb:
            for job in pick(persona, a.per_persona):
                for name, fn in archs.items():
                    if a.only and name not in a.only.split(","):
                        continue
                    t0 = time.perf_counter()
                    try:
                        dec, prop, toks = await fn(tb, persona, job, prof)
                        err = None
                    except Exception as e:
                        dec, prop, toks, err = "error", "", 0, f"{type(e).__name__}: {e}"[:200]
                    fc = check(prop, facts(persona), job["description"]) if prop else {"unsupported": 0, "claims": 0}
                    _, viol, _ = compliance.check_text(prop) if prop else ("", [], False)
                    rows.append({"arch": name, "persona": persona, "job_id": job["job_id"], "gold": job["gold"]["gold_decision"],
                                 "scam": job["gold"]["gold_scam"], "pred": dec, "unsupported": fc["unsupported"],
                                 "violations_in_output": len(viol), "tokens": toks, "latency_s": round(time.perf_counter() - t0, 1), "error": err})
                    print(rows[-1], flush=True)
    summary = {}
    for name in archs:
        rs = [r for r in rows if r["arch"] == name]
        if not rs:
            continue
        summary[name] = {"n": len(rs), "bid_skip_accuracy": round(mean([float(r["pred"] == r["gold"]) for r in rs]), 3),
                         "scams_bid_on": sum(r["scam"] and r["pred"] == "bid" for r in rs),
                         "unsupported_claims_per_proposal": round(mean([r["unsupported"] for r in rs if r["pred"] == "bid"]), 3),
                         "compliance_violations_left": sum(r["violations_in_output"] for r in rs),
                         "tokens_per_job": round(mean([r["tokens"] for r in rs]), 1), "p95_latency_s": pct([r["latency_s"] for r in rs], 95),
                         "errors": sum(bool(r["error"]) for r in rs)}
    print(summary)
    write("arch_compare.json", {"per_persona": a.per_persona, "summary": summary, "rows": rows})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=5)
    ap.add_argument("--only", default="")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
