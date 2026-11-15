"""Tracing setup: LangSmith when LANGSMITH_API_KEY is set, else self-hosted Arize Phoenix (OTel).

One trace id (uuid) is minted per UI request and used as the root `run_id` of the LangGraph run, passed to every
MCP tool call as `trace_id`, and written to the audit log - so UI -> API -> graph -> MCP -> audit share one id.
PII is masked at intake (untrusted job/message text) and by the LangSmith client's hide_inputs/hide_outputs hooks.
"""
from __future__ import annotations

import os
import uuid
from functools import lru_cache
from typing import Any

from common.pii import mask_obj


def new_trace_id() -> str:
    return str(uuid.uuid4())


@lru_cache(maxsize=1)
def backend() -> str:
    if os.environ.get("LANGSMITH_API_KEY"):
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGSMITH_PROJECT", "bidpilot")
        return "langsmith"
    endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT")
    if endpoint:
        try:
            from openinference.instrumentation.langchain import LangChainInstrumentor
            from phoenix.otel import register

            tp = register(project_name="bidpilot", endpoint=endpoint, set_global_tracer_provider=True, batch=True)
            LangChainInstrumentor().instrument(tracer_provider=tp)
            return "phoenix"
        except Exception as e:  # pragma: no cover
            print("phoenix tracing unavailable:", e)
    return "none"


def callbacks() -> list[Any]:
    if backend() == "langsmith":
        from langchain_core.tracers.langchain import LangChainTracer
        from langsmith import Client

        return [LangChainTracer(client=Client(hide_inputs=mask_obj, hide_outputs=mask_obj), project_name="bidpilot")]
    return []


def run_config(thread_id: str, trace_id: str, user_id: str, **extra: Any) -> dict[str, Any]:
    backend()
    return {
        "configurable": {"thread_id": thread_id, "user_id": user_id, "trace_id": trace_id, **extra},
        "run_id": uuid.UUID(trace_id),
        "run_name": f"bid:{thread_id}",
        "metadata": {"trace_id": trace_id, "user_id": user_id, "thread_id": thread_id},
        "tags": [os.environ.get("APP_ENV", "dev")],
        "callbacks": callbacks(),
        "recursion_limit": 60,
    }


def trace_url(trace_id: str) -> str | None:
    if backend() == "langsmith":
        org = os.environ.get("LANGSMITH_ORG_URL", "https://smith.langchain.com")
        return f"{org}/public/{trace_id}/r" if os.environ.get("LANGSMITH_PUBLIC") else f"{org}/o/-/projects/p/bidpilot/r/{trace_id}"
    if backend() == "phoenix":
        return f"{os.environ.get('PHOENIX_UI_URL', 'http://localhost:6006')}/projects/bidpilot"
    return None
