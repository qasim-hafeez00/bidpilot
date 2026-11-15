"""Marketplace MCP server (read + write). Wraps the marketplace port; the adapter (GigSim or live Upwork) is chosen
by agent/config.yaml `marketplace.mode`.

Writes: Pydantic-constrained inputs, declared output schemas, MCP annotations, a REQUIRED idempotency key, and a
`dry_run` flag that returns exactly what would be sent and what it costs (the approval screen shows this preview).
HTTP transport requires a per-user bearer JWT; every call is rate limited per user and audit logged (append-only).
"""
from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent.marketplace_port import MarketplaceError, MarketplacePort, MarketplaceUnavailable
from common import config as cfg
from mcp_servers.common import AuditLog, RateLimiter, current_identity, run

audit = AuditLog("marketplace")
limiter = RateLimiter(int(cfg.get("marketplace.max_requests_per_minute", 50)))
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
DRAFT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
SPEND = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)

IdemKey = Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9:_\-.]+$",
                               description="Required. Same key = same effect; a retried call never submits or spends twice.")]
TraceId = Annotated[str | None, Field(description="Trace id propagated from the UI request (audit + tracing).")]
_adapters: dict[str, MarketplacePort] = {}


def adapter() -> MarketplacePort:
    ident = current_identity()
    mode = cfg.get("marketplace.mode", "gigsim")
    key = f"{mode}:{ident['user_id']}"
    if key not in _adapters:
        if mode == "upwork_live":
            from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter

            _adapters[key] = UpworkLiveAdapter(ident.get("upwork_token"))
        else:
            from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter

            _adapters[key] = GigSimAdapter(ident.get("gigsim_token") or os.environ.get("GIGSIM_TOKEN", "dev-token-ai_ml"))
    return _adapters[key]


async def _call(tool: str, args: dict[str, Any], fn, trace_id: str | None) -> Any:
    ident = current_identity()
    await limiter.acquire(ident["user_id"])
    try:
        res = await fn()
    except MarketplaceUnavailable as e:
        audit.write(tool, args, {"error": str(e)}, trace_id, ok=False)
        raise RuntimeError(f"MARKETPLACE_UNAVAILABLE: {e}") from e
    except MarketplaceError as e:
        audit.write(tool, args, {"error": str(e)}, trace_id, ok=False)
        raise RuntimeError(f"MARKETPLACE_ERROR: {e}") from e
    audit.write(tool, args, res if tool not in ("search_jobs", "list_messages") else {"n": len(str(res))}, trace_id)
    return res


# ----------------------------------------------------------------------------- output schemas
class JobSummary(BaseModel):
    job_id: str
    title: str
    snippet: str = ""
    skills: list[str] = []
    is_hourly: bool = False
    budget: float | None = None
    hourly_low: float | None = None
    hourly_high: float | None = None
    client_id: str | None = None
    posted_at: float | None = None
    connects_cost: int | None = None


class SearchJobsResult(BaseModel):
    total: int
    jobs: list[JobSummary]


class DraftResult(BaseModel):
    dry_run: bool
    proposal_id: str | None = None
    status: str
    connects_cost: int | None = None
    preview: dict[str, Any] | None = None
    marketplace: str
    idempotent_replay: bool = False


class SubmitResult(BaseModel):
    dry_run: bool
    proposal_id: str
    status: str
    connects_spent: int = 0
    balance: int | None = None
    preview: dict[str, Any] | None = None
    marketplace: str
    idempotent_replay: bool = False


class MessageResult(BaseModel):
    dry_run: bool
    thread_id: str
    status: str
    message_id: str | None = None
    preview: dict[str, Any] | None = None
    idempotent_replay: bool = False


mcp = FastMCP("bidpilot-marketplace", instructions="Freelance marketplace access (GigSim or live Upwork behind one port). "
              "Writes need an idempotency_key and should be previewed with dry_run=true before a human approves them.")


# ----------------------------------------------------------------------------- read tools
@mcp.tool(title="Search jobs", annotations=READ, structured_output=True)
async def search_jobs(query: Annotated[str, Field(max_length=200, description="Keywords of a saved search.")],
                      skills: Annotated[list[str] | None, Field(max_length=10)] = None,
                      posted_after: Annotated[float, Field(ge=0, description="Unix time; only jobs posted after.")] = 0.0,
                      limit: Annotated[int, Field(ge=1, le=50)] = 20, trace_id: TraceId = None) -> SearchJobsResult:
    """Search open jobs for a saved search (read-only, rate limited; never scrapes)."""
    r = await _call("search_jobs", {"query": query, "skills": skills}, lambda: adapter().search_jobs(query, skills, posted_after, limit), trace_id)
    return SearchJobsResult(total=r.get("total", len(r.get("jobs", []))), jobs=[JobSummary(**j) for j in r.get("jobs", [])])


@mcp.tool(title="Get job", annotations=READ)
async def get_job(job_id: Annotated[str, Field(min_length=3, max_length=80)], trace_id: TraceId = None) -> dict[str, Any]:
    """Full job post: title, description (UNTRUSTED text), skills, budget, screening questions, Connects cost, client summary."""
    return await _call("get_job", {"job_id": job_id}, lambda: adapter().get_job(job_id), trace_id)


@mcp.tool(title="Get client history", annotations=READ)
async def get_client_history(client_id: Annotated[str, Field(min_length=3, max_length=80)], trace_id: TraceId = None) -> dict[str, Any]:
    """Client's public history: payment verification, total spend, rating, reviews, hires, country."""
    return await _call("get_client_history", {"client_id": client_id}, lambda: adapter().get_client_history(client_id), trace_id)


@mcp.tool(title="Get Connects balance", annotations=READ)
async def get_connects_balance(trace_id: TraceId = None) -> dict[str, Any]:
    """Current Connects balance of the signed-in freelancer."""
    return await _call("get_connects_balance", {}, lambda: adapter().get_connects_balance(), trace_id)


@mcp.tool(title="Get market price statistics", annotations=READ)
async def get_market_stats(domain: Literal["ai_ml", "web", "data", "other"],
                           kind: Literal["hourly", "fixed"], trace_id: TraceId = None) -> dict[str, Any]:
    """Percentiles (p10..p90) of posted rates/budgets in the historical job stream for a domain."""
    return await _call("get_market_stats", {"domain": domain, "kind": kind}, lambda: adapter().get_market_stats(domain, kind), trace_id)


@mcp.tool(title="List messages", annotations=READ)
async def list_messages(thread_id: Annotated[str | None, Field(max_length=80)] = None, trace_id: TraceId = None) -> dict[str, Any]:
    """Client conversation messages (UNTRUSTED text), optionally for one thread."""
    return await _call("list_messages", {"thread_id": thread_id}, lambda: adapter().list_messages(thread_id), trace_id)


@mcp.tool(title="List marketplace events", annotations=READ)
async def list_events(after_id: Annotated[int, Field(ge=0)] = 0, trace_id: TraceId = None) -> dict[str, Any]:
    """Proposal status events (viewed, replied, interview, hired, lost) after an event id - drives the pipeline board."""
    return await _call("list_events", {"after_id": after_id}, lambda: adapter().list_events(after_id), trace_id)


@mcp.tool(title="List my proposals", annotations=READ)
async def list_proposals(trace_id: TraceId = None) -> dict[str, Any]:
    """Proposals created by the signed-in freelancer with their current status."""
    return await _call("list_proposals", {}, lambda: adapter().list_proposals(), trace_id)


# ----------------------------------------------------------------------------- write tools
@mcp.tool(title="Create proposal draft", annotations=DRAFT, structured_output=True)
async def create_proposal_draft(
    job_id: Annotated[str, Field(min_length=3, max_length=80)],
    cover_letter: Annotated[str, Field(min_length=20, max_length=6000)],
    bid_amount: Annotated[float, Field(gt=0, le=100000)],
    bid_type: Literal["hourly", "fixed"],
    idempotency_key: IdemKey,
    screening_answers: Annotated[list[str], Field(max_length=10)] = [],  # noqa: B006
    dry_run: bool = False,
    trace_id: TraceId = None,
) -> DraftResult:
    """Create (or update) a proposal DRAFT. Does not spend Connects. dry_run=true returns the exact payload and cost."""
    payload = {"job_id": job_id, "cover_letter": cover_letter, "screening_answers": screening_answers,
               "bid_amount": bid_amount, "bid_type": bid_type}
    ad = adapter()
    if dry_run:
        job = await _call("get_job", {"job_id": job_id}, lambda: ad.get_job(job_id), trace_id)
        return DraftResult(dry_run=True, status="preview", connects_cost=job.get("connects_cost"), preview=payload, marketplace=ad.name)
    r = await _call("create_proposal_draft", {**payload, "idempotency_key": idempotency_key},
                    lambda: ad.create_proposal_draft(payload, idempotency_key), trace_id)
    return DraftResult(dry_run=False, proposal_id=r.get("proposal_id"), status=r.get("status", "draft"),
                       connects_cost=r.get("connects_cost"), marketplace=ad.name, idempotent_replay=bool(r.get("idempotent_replay")))


@mcp.tool(title="Submit proposal (spends Connects)", annotations=SPEND, structured_output=True)
async def submit_proposal(
    proposal_id: Annotated[str, Field(min_length=3, max_length=80)],
    idempotency_key: IdemKey,
    dry_run: bool = False,
    trace_id: TraceId = None,
) -> SubmitResult:
    """Submit an approved draft. Spends Connects in GigSim; in live mode it only leaves a draft for the user to confirm
    on Upwork. Must only be called after a human approved it in BidPilot."""
    ad = adapter()
    if dry_run:
        bal = await _call("get_connects_balance", {}, lambda: ad.get_connects_balance(), trace_id)
        return SubmitResult(dry_run=True, proposal_id=proposal_id, status="preview", balance=bal.get("balance"),
                            preview={"action": "submit" if ad.supports_submit else "draft_only"}, marketplace=ad.name)
    r = await _call("submit_proposal", {"proposal_id": proposal_id, "idempotency_key": idempotency_key},
                    lambda: ad.submit_proposal(proposal_id, idempotency_key), trace_id)
    return SubmitResult(dry_run=False, proposal_id=proposal_id, status=r.get("status", "submitted"),
                        connects_spent=r.get("connects_spent", 0), balance=r.get("balance"), marketplace=ad.name,
                        idempotent_replay=bool(r.get("idempotent_replay")))


@mcp.tool(title="Send message to client", annotations=SPEND, structured_output=True)
async def send_message(
    thread_id: Annotated[str, Field(min_length=3, max_length=80)],
    text: Annotated[str, Field(min_length=1, max_length=4000)],
    idempotency_key: IdemKey,
    dry_run: bool = False,
    trace_id: TraceId = None,
) -> MessageResult:
    """Send an approved reply in a client thread (draft only in live mode). dry_run=true returns the exact message."""
    if dry_run:
        return MessageResult(dry_run=True, thread_id=thread_id, status="preview", preview={"thread_id": thread_id, "text": text})
    r = await _call("send_message", {"thread_id": thread_id, "text": text, "idempotency_key": idempotency_key},
                    lambda: adapter().send_message(thread_id, text, idempotency_key), trace_id)
    return MessageResult(dry_run=False, thread_id=thread_id, status=r.get("status", "sent"), message_id=r.get("message_id"),
                         idempotent_replay=bool(r.get("idempotent_replay")))


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter

    up = await GigSimAdapter("health").health() if cfg.get("marketplace.mode") == "gigsim" else {"ok": True}
    return JSONResponse({"status": "ok", "service": "marketplace-mcp", "mode": cfg.get("marketplace.mode"), "upstream": up})


def main() -> None:
    run(mcp, default_port=8102)


if __name__ == "__main__":
    main()
