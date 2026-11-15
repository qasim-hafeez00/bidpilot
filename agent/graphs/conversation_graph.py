"""Conversation graph - one thread per client conversation (C1).

  read_messages -> classify --interview_request--> slots -> draft_reply
                           \--question/negotiation/scam_signal/other-----> draft_reply
  draft_reply --blocked--> END
              --ok--> approve [interrupt] --approved--> send -> END
                                          --rejected--> END
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agent.graphs._guard import guard, halted
from agent.nodes import client_liaison as cl
from agent.state import ConversationState


def after_classify(state: dict[str, Any]) -> str:
    if halted(state):
        return END
    return "slots" if state.get("intent", {}).get("intent") == "interview_request" else "draft_reply"


def after_draft(state: dict[str, Any]) -> str:
    return END if halted(state) else "approve"


def after_approve(state: dict[str, Any]) -> str:
    return {"approved": "send", "awaiting_approval": "approve"}.get(state.get("status"), END)


def build_conversation_graph(checkpointer=None, store=None):
    g = StateGraph(ConversationState)
    g.add_node("read_messages", guard("read_messages", cl.read_messages))
    g.add_node("classify", guard("classify", cl.classify))
    g.add_node("slots", guard("slots", cl.slots))
    g.add_node("draft_reply", guard("client_liaison", cl.draft_reply))
    g.add_node("approve", guard("approve", cl.approve))
    g.add_node("send", guard("send", cl.send))
    g.add_edge(START, "read_messages")
    g.add_conditional_edges("read_messages", lambda s: END if halted(s) or not s.get("last_client_message") else "classify",
                            ["classify", END])
    g.add_conditional_edges("classify", after_classify, ["slots", "draft_reply", END])
    g.add_conditional_edges("slots", lambda s: END if halted(s) else "draft_reply", ["draft_reply", END])
    g.add_conditional_edges("draft_reply", after_draft, ["approve", END])
    g.add_conditional_edges("approve", after_approve, ["send", "approve", END])
    g.add_edge("send", END)
    return g.compile(checkpointer=checkpointer, store=store)
