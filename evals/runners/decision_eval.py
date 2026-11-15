"""Decision evaluation on the dev set: bid-or-skip F1, scam precision/recall, injection detection, price inside the fair
band, and latency per job analysed. Runs the REAL bid graph (analysis_only) through the in-memory MCP client.

    python -m evals.runners.decision_eval [--split dev] [--limit 0] [--out decision_eval.json]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from collections import defaultdict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from agent.graphs.bid_graph import build_bid_graph
from agent.mcp_client import InMemoryToolBox
from agent.nodes.pricing import quote
from common.tracing import run_config
from evals.runners.common import PERSONAS, RESULTS, ROOT, load_jobs, mean, pct, write


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0, "tp": tp, "fp": fp, "fn": fn}


async def run_persona(persona: str, split: str, limit: int, concurrency: int = 4) -> list[dict]:
    prof = json.loads((ROOT / "data" / "personas" / persona / "profile.json").read_text())
    settings = {"hourly_floor": prof["hourly_floor"], "min_fixed": prof["min_fixed"], "weekly_connects_budget": 10**6, "analysis_only": True}
    stats = json.loads((ROOT / "data" / "gigsim_seed" / "market_stats.json").read_text())
    jobs = load_jobs(persona, split)[: limit or None]
    rows: list[dict] = []
    async with InMemoryToolBox(f"eval-{persona}", persona, f"dev-token-{persona}") as tb:
        g = build_bid_graph(MemorySaver(), InMemoryStore())
        sem = asyncio.Semaphore(concurrency)

        async def one(j: dict) -> None:
            async with sem:
                public = {k: v for k, v in j.items() if k not in ("gold", "persona_id", "scam_type", "injected")}
                public["client_summary"] = j.get("client")
                cfg = run_config(f"eval:{persona}:{j['job_id']}", "00000000-0000-4000-8000-" + f"{abs(hash(j['job_id'])) % 10**12:012d}",
                                 "eval", toolbox=tb)
                t0 = time.perf_counter()
                st = await g.ainvoke({"job_id": j["job_id"], "job": public, "user_id": "eval", "persona": persona, "settings": settings}, cfg)
                dt = time.perf_counter() - t0
                gold = j["gold"]
                action = (st.get("decision") or {}).get("action", "error")
                risk = st.get("risk_report") or {}
                q = quote(public, stats.get(f"{(st.get('job_spec') or {}).get('domain', 'other')}:{'hourly' if j['is_hourly'] else 'fixed'}",
                                            stats["other:hourly"]), settings, float((st.get("fit_report") or {}).get("score", 0.5)))
                lo, hi = gold["gold_price_band"]
                rows.append({"persona": persona, "job_id": j["job_id"], "job_type": gold["job_type"], "gold": gold["gold_decision"],
                             "pred": action, "status": st.get("status"), "fit": (st.get("fit_report") or {}).get("score"),
                             "risk": risk.get("score"), "scam_pred": risk.get("scam_likelihood", 0) >= 0.5, "scam_gold": gold["gold_scam"],
                             "inj_pred": bool(risk.get("injection_detected")), "inj_gold": gold["gold_injection"],
                             "price": q.amount, "band_lo": lo, "band_hi": hi, "price_in_band": lo <= q.amount <= hi,
                             "price_ok_gold": gold["gold_price_ok"], "latency_s": round(dt, 3), "flags": "|".join(risk.get("flags", []))})

        await asyncio.gather(*(one(j) for j in jobs))
    return rows


def summarize(rows: list[dict]) -> dict:
    def block(rs: list[dict]) -> dict:
        b = prf(sum(r["pred"] == "bid" and r["gold"] == "bid" for r in rs), sum(r["pred"] == "bid" and r["gold"] != "bid" for r in rs),
                sum(r["pred"] != "bid" and r["gold"] == "bid" for r in rs))
        s = prf(sum(r["scam_pred"] and r["scam_gold"] for r in rs), sum(r["scam_pred"] and not r["scam_gold"] for r in rs),
                sum(not r["scam_pred"] and r["scam_gold"] for r in rs))
        inj = [r for r in rs if r["inj_gold"]]
        bidgold = [r for r in rs if r["gold"] == "bid"]
        return {"n": len(rs), "bid_skip": b, "accuracy": round(mean([float((r["pred"] == "bid") == (r["gold"] == "bid")) for r in rs]), 4),
                "scam": s, "injection_detection_recall": round(mean([float(r["inj_pred"]) for r in inj]), 4) if inj else None,
                "injection_false_positive_rate": round(mean([float(r["inj_pred"]) for r in rs if not r["inj_gold"]]), 4),
                "price_in_fair_band": round(mean([float(r["price_in_band"]) for r in bidgold]), 4) if bidgold else None,
                "watch_rate": round(mean([float(r["pred"] == "watch") for r in rs]), 4),
                "latency_p50_s": round(pct([r["latency_s"] for r in rs], 50), 3), "latency_p95_s": round(pct([r["latency_s"] for r in rs], 95), 3)}

    out = {"overall": block(rows), "by_persona": {}, "by_job_type": {}}
    g = defaultdict(list)
    for r in rows:
        g[r["persona"]].append(r)
    out["by_persona"] = {k: block(v) for k, v in g.items()}
    g = defaultdict(list)
    for r in rows:
        g[r["job_type"].replace("_multi_req", "")].append(r)
    out["by_job_type"] = {k: block(v) for k, v in g.items()}
    return out


async def main_async(a) -> None:
    rows = []
    for p in PERSONAS:
        t0 = time.time()
        rows += await run_persona(p, a.split, a.limit, a.concurrency)
        print(p, "done", round(time.time() - t0), "s")
    s = summarize(rows)
    o = s["overall"]
    print(f"bid F1={o['bid_skip']['f1']} acc={o['accuracy']} scam P={o['scam']['precision']} R={o['scam']['recall']} "
          f"inj={o['injection_detection_recall']} price_in_band={o['price_in_fair_band']} p95={o['latency_p95_s']}s")
    write(a.out, {"split": a.split, "limit": a.limit, **s})
    with open(RESULTS / a.out.replace(".json", "_rows.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", default="decision_eval.json")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
