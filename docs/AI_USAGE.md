# AI usage disclosure

| Tool | Used for |
|---|---|
| Claude Code (Anthropic) | Most of the code across `agent/`, `rag/`, `mcp_servers/`, `apps/`, `gigsim/`, `scripts/` and `evals/`, the docs, and the LaTeX report skeleton, written under my direction and reviewed by me. |

## Things it got wrong that were caught

1. **Slow data builder.** The first skill extractor ran about 500 separate regexes per job across 110k jobs and was killed after 10+ minutes.
   It was replaced with a substring-prefiltered matcher (97 s end to end).
2. **Gold-label bug.** A Solidity/NFT job was labelled "bid" for the full-stack persona because React and JS covered 2 of 3 skills.
   Fixed by requiring all core (title) skills.
3. **MCP session lifecycle.** Sessions were entered in one asyncio task and closed in another, which crashed anyio on shutdown. Fixed
   with one owner task per session.
4. **Port assumption.** It assumed GigSim's default port 8081 was free; another local service answered with HTML. Ports were moved to the 18xxx range.
5. **Missing output schemas.** The pinned MCP SDK (1.8.0) did not support declared output schemas, which A2 requires. Upgraded to 1.12.4.

I am accountable for every line. Numbers in the report come only from `evals/results/`.
