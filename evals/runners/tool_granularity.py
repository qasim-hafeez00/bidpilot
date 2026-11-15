"""R&D question A: does tool granularity change agent behaviour?

40 tasks with a known correct call. Three tool sets are bound to the same model (one turn, tool choice only):
  fine     - the real MCP tools (14) with their original one-line descriptions
  coarse   - 3 tools (marketplace / portfolio / workspace) with an `action` enum + free-form args
  best     - the fine tools with rewritten "use when..." descriptions and argument examples
Metrics: tool-selection accuracy, argument accuracy, tokens per task.
"""
from __future__ import annotations

import argparse
import json
import random
import time

from common.llm import chat_model, model_for
from evals.runners.common import mean, write

FINE = {
    "search_jobs": ("Search open jobs.", {"query": "string"}),
    "get_job": ("Get a job.", {"job_id": "string"}),
    "get_client_history": ("Client history.", {"client_id": "string"}),
    "get_connects_balance": ("Connects balance.", {}),
    "get_market_stats": ("Market stats.", {"domain": "ai_ml|web|data|other", "kind": "hourly|fixed"}),
    "list_messages": ("List messages.", {"thread_id": "string"}),
    "list_proposals": ("List proposals.", {}),
    "search_evidence": ("Search evidence.", {"requirement": "string"}),
    "get_case_study": ("Get case study.", {"id": "string"}),
    "list_skills": ("List skills.", {}),
    "get_free_slots": ("Free slots.", {"start_date": "YYYY-MM-DD"}),
    "create_interview_hold": ("Interview hold.", {"start": "ISO datetime", "title": "string"}),
    "create_email_draft": ("Email draft.", {"to_label": "string", "subject": "string", "body": "string"}),
    "create_proposal_draft": ("Proposal draft.", {"job_id": "string", "cover_letter": "string", "bid_amount": "number"}),
}
BEST_DESC = {
    "search_jobs": "Use to FIND jobs on the marketplace by keywords, e.g. query='django api'. Not for one known job id.",
    "get_job": "Use when you already have a job id (e.g. 'dai-0001-e39ee2') and need its full post.",
    "get_client_history": "Use to check a CLIENT's reputation by client id (e.g. 'cl-1a2b3c4d'): spend, rating, verification.",
    "get_connects_balance": "Use when asked how many Connects (bidding credits) the freelancer has left.",
    "get_market_stats": "Use for typical market RATES/BUDGETS for a domain (ai_ml, web, data, other) and kind (hourly|fixed).",
    "list_messages": "Use to read a client CONVERSATION by thread id (e.g. 'th-pr-1234').",
    "list_proposals": "Use to list proposals the freelancer already submitted and their status.",
    "search_evidence": "Use to find PORTFOLIO proof of a skill or requirement, e.g. requirement='Celery background jobs'.",
    "get_case_study": "Use to open ONE case study by id, e.g. id='ai_ml:legal-rag'.",
    "list_skills": "Use to list every skill the freelancer's portfolio evidences.",
    "get_free_slots": "Use to find free CALENDAR times for an interview starting on start_date (YYYY-MM-DD).",
    "create_interview_hold": "Use to put a TENTATIVE interview hold on the calendar at an ISO start time.",
    "create_email_draft": "Use to save an EMAIL DRAFT (never sent).",
    "create_proposal_draft": "Use to save a PROPOSAL DRAFT for a job id with a cover letter and bid amount (does not submit).",
}
COARSE = {
    "marketplace": ("Marketplace operations.", {"action": "search_jobs|get_job|get_client_history|get_connects_balance|get_market_stats|"
                                                           "list_messages|list_proposals|create_proposal_draft", "args": "object"}),
    "portfolio": ("Portfolio operations.", {"action": "search_evidence|get_case_study|list_skills", "args": "object"}),
    "workspace": ("Calendar and email.", {"action": "get_free_slots|create_interview_hold|create_email_draft", "args": "object"}),
}
COARSE_OF = {t: s for s, (_, a) in COARSE.items() for t in a["action"].split("|")}


def tasks() -> list[dict]:
    r = random.Random(1)
    T = []
    for q in ["django rest api", "power bi dashboard", "llm chatbot", "react native app", "airflow etl", "computer vision yolo"]:
        T.append({"prompt": f"Find me new jobs about {q}.", "tool": "search_jobs", "check": {"query": q.split()[0]}})
    for jid in ["dai-0001-e39ee2", "dfu-0042-a1b2c3", "dda-0107-ffee01", "dai-0150-0a0b0c"]:
        T.append({"prompt": f"Show me the full post for job {jid}.", "tool": "get_job", "check": {"job_id": jid}})
    for cid in ["cl-1a2b3c4d", "cl-9f8e7d6c", "cl-00aa11bb"]:
        T.append({"prompt": f"Is client {cid} trustworthy? Check their history.", "tool": "get_client_history", "check": {"client_id": cid}})
    T += [{"prompt": p, "tool": "get_connects_balance", "check": {}} for p in ["How many Connects do I have left?", "What's my bidding credit balance?"]]
    for d, k in [("data", "hourly"), ("web", "fixed"), ("ai_ml", "hourly")]:
        T.append({"prompt": f"What do {d.replace('_', '/')} freelancers typically charge ({k})?", "tool": "get_market_stats", "check": {"domain": d, "kind": k}})
    for th in ["th-pr-11aa", "th-pr-77cd"]:
        T.append({"prompt": f"Read the conversation in thread {th}.", "tool": "list_messages", "check": {"thread_id": th}})
    T.append({"prompt": "Which proposals have I already sent?", "tool": "list_proposals", "check": {}})
    for s in ["Celery", "dbt", "Pinecone", "YOLO", "Stripe", "Tableau"]:
        T.append({"prompt": f"Do I have any portfolio proof that I've used {s}?", "tool": "search_evidence", "check": {"requirement": s.lower()}})
    for c in ["ai_ml:legal-rag", "fullstack:drf-api", "data_analyst:sales-powerbi"]:
        T.append({"prompt": f"Open my case study {c}.", "tool": "get_case_study", "check": {"id": c}})
    T.append({"prompt": "List all the skills my portfolio can prove.", "tool": "list_skills", "check": {}})
    for d in ["2026-11-20", "2026-12-01"]:
        T.append({"prompt": f"When am I free for a 30 minute interview from {d}?", "tool": "get_free_slots", "check": {"start_date": d}})
    T.append({"prompt": "Put a tentative hold for the client interview on 2026-11-21T10:00:00+05:00.", "tool": "create_interview_hold", "check": {"start": "2026-11-21"}})
    T.append({"prompt": "Draft an email to the Acme client thanking them for the call.", "tool": "create_email_draft", "check": {"to_label": "acme"}})
    T.append({"prompt": "Save a proposal draft for job dai-0001-e39ee2 at $40 with the letter 'I built a RAG assistant...'.",
              "tool": "create_proposal_draft", "check": {"job_id": "dai-0001-e39ee2"}})
    while len(T) < 40:  # paraphrased duplicates to reach 40
        t = dict(r.choice(T))
        t["prompt"] = "Please: " + t["prompt"].lower()
        T.append(t)
    return T[:40]


def schema(name: str, desc: str, args: dict) -> dict:
    props = {k: ({"type": "object"} if v == "object" else {"type": "number"} if v == "number" else {"type": "string", "description": v}) for k, v in args.items()}
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {"type": "object", "properties": props, "required": list(args)}}}


def toolset(kind: str) -> list[dict]:
    if kind == "coarse":
        return [schema(n, d, a) for n, (d, a) in COARSE.items()]
    return [schema(n, BEST_DESC[n] if kind == "best" else d, a) for n, (d, a) in FINE.items()]


def score(kind: str, task: dict, call: dict | None) -> tuple[bool, bool]:
    if not call:
        return False, False
    name, args = call["name"], call.get("args") or {}
    if kind == "coarse":
        sel = name == COARSE_OF[task["tool"]] and args.get("action") == task["tool"]
        args = args.get("args") or {k: v for k, v in args.items() if k != "action"}
    else:
        sel = name == task["tool"]
    ok = sel and all(str(v).lower() in json.dumps(args).lower() for v in task["check"].values())
    return sel, ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()
    from langchain_core.messages import HumanMessage, SystemMessage

    prov, mdl = model_for("scout")
    llm = chat_model(prov, mdl, max_tokens=200, temperature=0.0)
    out = {}
    for kind in ("fine", "coarse", "best"):
        bound = llm.bind_tools(toolset(kind))
        sels, args_ok, toks, lat = [], [], [], []
        for t in tasks()[: a.limit]:
            t0 = time.perf_counter()
            msg = bound.invoke([SystemMessage("You are a freelancing assistant. Call exactly one tool for the user's request."), HumanMessage(t["prompt"])])
            lat.append(time.perf_counter() - t0)
            call = msg.tool_calls[0] if msg.tool_calls else None
            s, ok = score(kind, t, call)
            sels.append(float(s))
            args_ok.append(float(ok))
            um = msg.usage_metadata or {}
            toks.append(um.get("input_tokens", 0) + um.get("output_tokens", 0))
        out[kind] = {"tool_selection_accuracy": round(mean(sels), 3), "argument_accuracy": round(mean(args_ok), 3),
                     "tokens_per_task": round(mean(toks), 1), "mean_latency_s": round(mean(lat), 2), "n": len(sels)}
        print(kind, out[kind], flush=True)
    write("tool_granularity.json", {"model": mdl, "results": out})


if __name__ == "__main__":
    main()
