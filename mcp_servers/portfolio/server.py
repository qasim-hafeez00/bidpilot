"""Portfolio MCP server (read-only). Usable from Claude Desktop / Cursor:

    uvx --from git+https://github.com/qasim-hafeez00/bidpilot bidpilot-portfolio-mcp     # stdio
    python -m mcp_servers.portfolio.server --transport http --port 8101                 # Streamable HTTP + bearer
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_servers.common import run
from mcp_servers.portfolio import prompts, resources, tools

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

mcp = FastMCP(
    "bidpilot-portfolio",
    instructions="Read-only access to a freelancer's portfolio: case studies, repos/code, reviews, CV and past proposals "
                 "with outcomes. Use search_evidence to prove a job requirement; cite evidence_id values.",
)

mcp.tool(title="Search portfolio evidence", annotations=READ_ONLY, structured_output=True)(tools.search_evidence)
mcp.tool(title="Get case study", annotations=READ_ONLY, structured_output=True)(tools.get_case_study)
mcp.tool(title="List evidenced skills", annotations=READ_ONLY, structured_output=True)(tools.list_skills)
resources.register(mcp)
prompts.register(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "portfolio-mcp", "variant": os.environ.get("RAG_VARIANT", "config")})


@mcp.custom_route("/admin/reindex", methods=["POST"])
async def reindex(request: Request) -> JSONResponse:
    """Incremental re-index after the user uploads work in the UI (admin token; not an agent tool)."""
    from pathlib import Path

    from rag.index.store import add_documents, invalidate
    from rag.ingest.loaders import load_uploads

    body = await request.json()
    owner, persona = body["owner"], body.get("persona", body["owner"])
    n = add_documents(persona, load_uploads(owner, Path(body["upload_dir"]))) if body.get("upload_dir") else 0
    if not n:
        invalidate(persona)
    return JSONResponse({"reindexed": persona, "documents_added": n})


def main() -> None:
    run(mcp, default_port=8101)


if __name__ == "__main__":
    main()
