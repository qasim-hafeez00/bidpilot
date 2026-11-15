"""Resource templates so a host can load full portfolio items."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_servers.portfolio import tools
from rag.ingest.loaders import PERSONA_ROOT


def register(mcp: FastMCP) -> None:
    @mcp.resource("portfolio://case/{id}", name="case_study", mime_type="text/markdown",
                  description="Full Markdown case study by project id (e.g. ai_ml:legal-rag).")
    def case(id: str) -> str:
        return tools.get_case_study(id).markdown

    @mcp.resource("portfolio://proposal/{id}", name="past_proposal", mime_type="application/json",
                  description="A past proposal with its outcome (won / replied / ignored).")
    def proposal(id: str) -> str:
        return tools.proposal_json(id)

    @mcp.resource("portfolio://cv/{persona}", name="cv", mime_type="text/markdown", description="The freelancer's CV.")
    def cv(persona: str) -> str:
        return (PERSONA_ROOT / persona / "cv" / "cv.md").read_text(encoding="utf-8")
