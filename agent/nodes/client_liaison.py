"""Client Liaison: read client replies, classify intent, draft a response or interview slots, send after approval.

Marketplace (read; write after approval) + Workspace via MCP.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Any

from langgraph.types import interrupt

from agent.handoffs import Approval, MessageIntent
from agent.nodes import compliance
from agent.nodes._util import injection_spans, rec, toolbox, trace_id, untrusted
from common import config as cfg
from common.llm import LLMUnavailable, chat, parse_json

RULES = [
    ("scam_signal", r"telegram|whatsapp|skype|signal|gift ?card|crypto|outside (the )?platform|for free as a test|pay (only )?after|wire|bank"),
    ("interview_request", r"\b(call|interview|meet|schedule|zoom|slots?|times? work|available)\b"),
    ("negotiation", r"\b(budget|rate|price|cheaper|discount|lower|fixed price|could you do it for|\$\s?\d+)\b"),
    ("question", r"\?|\b(how|what|when|which|can you|could you)\b"),
]


def classify_rules(text: str) -> MessageIntent:
    for intent, pat in RULES:
        if re.search(pat, text, re.I):
            return MessageIntent(intent=intent, confidence=0.75 if intent != "question" else 0.6, reason=f"rule:{intent}")
    return MessageIntent(intent="other", confidence=0.3, reason="no rule matched")


async def read_messages(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    tb, tid = toolbox(config), trace_id(state, config)
    msgs = (await tb.call("client_liaison", "list_messages", {"thread_id": state["thread_id"]}, tid)).get("messages", [])
    last = next((m for m in reversed(msgs) if m["sender"] == "client"), None)
    job = state.get("job") or {}
    if not job and state.get("job_id"):
        job = await tb.call("client_liaison", "get_job", {"job_id": state["job_id"]}, tid)
    return {"messages": [{**m, "text": untrusted(m["text"])} for m in msgs], "job": job,
            "last_client_message": {**last, "text": untrusted(last["text"])} if last else {}, "steps": 1,
            "trace": [rec("liaison.read", tool="list_messages", n=len(msgs))]}


async def classify(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    text = state.get("last_client_message", {}).get("text", "")
    it = classify_rules(text)
    usage = []
    if cfg.get("models.use_llm.intent", True) and it.confidence < 0.7 and it.intent != "scam_signal":
        try:
            r = await chat("intent", "intent", json_mode=True, max_tokens=80, config=config, message=text[:1500])
            usage.append(r.usage("intent"))
            d = parse_json(r.text)
            if d.get("intent") in ("question", "negotiation", "interview_request", "scam_signal", "other"):
                it = MessageIntent(intent=d["intent"], confidence=float(d.get("confidence", 0.6)), reason="llm: " + str(d.get("reason", ""))[:80])
        except (LLMUnavailable, ValueError) as e:
            usage.append({"node": "intent", "error": str(e)[:200]})
    if injection_spans(text):
        it.reason += " (+ injected instructions ignored)"
    return {"intent": it.model_dump(), "usage": usage, "steps": 1, "trace": [rec("liaison.classify", intent=it.intent, how=it.reason)]}


async def slots(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    start = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    s = await toolbox(config).call("client_liaison", "get_free_slots", {"start_date": start, "days": 5, "duration_min": 30},
                                   trace_id(state, config))
    return {"slots": s.get("slots", []), "steps": 1, "trace": [rec("liaison.slots", tool="get_free_slots", n=len(s.get("slots", [])))]}


SCAM_REPLY = ("Thanks for getting back to me. I keep all communication and payments on this platform, as its terms require, "
              "and I don't take on unpaid test work. If you'd like to continue here, I'm happy to answer any questions about the project.")


async def draft_reply(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    intent = state["intent"]["intent"]
    msg = state.get("last_client_message", {}).get("text", "")
    settings = state.get("settings", {})
    usage = []
    if intent == "scam_signal":
        text = SCAM_REPLY
    else:
        hist = "\n".join(f"{m['sender']}: {m['text'][:300]}" for m in state.get("messages", [])[-6:])
        slot_txt = ("OFFER THESE INTERVIEW SLOTS (copy them exactly): " + "; ".join(s["label"] for s in state.get("slots", []))) if state.get("slots") else ""
        ev = "; ".join(f"{e.get('title')}: {e.get('snippet', '')[:160]}" for e in state.get("evidence", [])[:3]) or "see proposal"
        try:
            r = await chat("client_liaison", "client_liaison", max_tokens=220, config=config, job_title=state.get("job", {}).get("title", ""),
                           history=hist, intent=intent, message=msg[:1200], evidence=ev, bid=state.get("bid", "as proposed"),
                           floor=settings.get("hourly_floor", 0), slots_text=slot_txt)
            usage.append(r.usage("client_liaison"))
            text = r.text.strip()
        except LLMUnavailable as e:
            usage.append({"node": "client_liaison", "error": str(e)[:200], "fallback": "template"})
            text = {"interview_request": "Happy to talk. These times work for me: " + "; ".join(s["label"] for s in state.get("slots", [])) + ". Which suits you?",
                    "negotiation": f"Thanks for the transparency. My rate reflects the scope; I can adjust scope to fit the budget but can't go below ${settings.get('hourly_floor', '')}/h.",
                    }.get(intent, "Thanks for the question - happy to clarify. Could you share a bit more detail so I can answer precisely?")
        if state.get("slots") and intent == "interview_request" and not any(s["label"][:10] in text for s in state["slots"]):
            text += " Available: " + "; ".join(s["label"] for s in state["slots"]) + "."
    verdict = compliance.evaluate(text, [], False)
    if verdict.status == "fixed":
        text = verdict.fixed_text
    return {"reply": {"thread_id": state["thread_id"], "text": text, "intent": intent, "slots": state.get("slots", [])},
            "compliance_verdict": verdict.model_dump(), "usage": usage, "steps": 1,
            "status": "blocked" if verdict.status == "block" else "awaiting_approval",
            "trace": [rec("liaison.draft", intent=intent, words=len(text.split()), compliance=verdict.status)]}


async def approve(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    raw = interrupt({"kind": "message", "thread_id": state["thread_id"], "client_message": state.get("last_client_message"),
                     "intent": state.get("intent"), "reply": state.get("reply"), "slots": state.get("slots", []),
                     "compliance": state.get("compliance_verdict"),
                     "dry_run": {"thread_id": state["thread_id"], "text": state.get("reply", {}).get("text")}})
    a = Approval(**raw)
    out: dict[str, Any] = {"approvals": [a.model_dump()], "steps": 1}
    if a.action == "reject":
        return {**out, "status": "rejected", "trace": [rec("liaison.approval", action="reject", reason=a.reason)]}
    reply = dict(state["reply"])
    if a.action == "edit" and a.edited_text:
        v = compliance.evaluate(a.edited_text, [], False)
        if v.status == "block":
            return {**out, "status": "awaiting_approval", "compliance_verdict": v.model_dump()}
        reply["text"] = v.fixed_text or a.edited_text
    return {**out, "reply": reply, "status": "approved", "trace": [rec("liaison.approval", action=a.action)]}


async def send(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    tb, tid = toolbox(config), trace_id(state, config)
    reply = state["reply"]
    key = "bpm-" + hashlib.sha256(f"{state.get('user_id')}:{state['thread_id']}:{reply['text']}".encode()).hexdigest()[:32]
    r = await tb.call("liaison_sender", "send_message", {"thread_id": state["thread_id"], "text": reply["text"], "idempotency_key": key}, tid)
    trace = [rec("liaison.send", tool="send_message", replay=r.get("idempotent_replay"))]
    if reply.get("slots") and reply.get("intent") == "interview_request":
        s0 = reply["slots"][0]
        h = await tb.call("liaison_sender", "create_interview_hold", {"start": s0["start"], "duration_min": 30,
                                                                       "title": f"Interview: {state.get('job', {}).get('title', '')[:80]}",
                                                                       "idempotency_key": key + "-hold"}, tid)
        trace.append(rec("liaison.hold", tool="create_interview_hold", hold=h.get("hold_id")))
    return {"sent": r, "status": "sent", "steps": 1, "trace": trace}
