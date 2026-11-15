# Architecture decision records

Each record gives the context, the decision, and its consequence.

## ADR-1: Rules-first nodes, LLM where it adds value
* **Context:** CPU-only laptop, where Qwen2.5-3B runs at 6 tok/s. The analysis budget is p95 ≤ 20 s per job.
* **Decision:** Analyst, Risk, Decision, Pricing and Compliance are deterministic by default. Their LLM refinements are config switches.
  The Writer (and optionally the Critic and Liaison) use the LLM.
* **Consequence:** about 70% of jobs (skips) cost 0 LLM tokens. Hidden needs are only extracted when `use_llm.analyst` is on.

## ADR-2: One composable retrieval pipeline; variants are presets
* **Context:** V0–V8 must be compared and ablated.
* **Decision:** `rag/pipeline.py` exposes flags. Each variant file is a preset, and the ablation flips one flag at a time.
* **Consequence:** one command reruns everything. The variant shipped is a config value chosen from `rag_variants.json`.

## ADR-3: The Marketplace MCP server owns the port adapter
* **Context:** R1 requires one port and two adapters; R2 requires agents to use MCP only.
* **Decision:** Agents call the Marketplace MCP tools. The server instantiates the GigSim or Upwork adapter from `marketplace.mode`.
* **Consequence:** the graph cannot tell which marketplace it uses. Live mode can only create drafts.

## ADR-4: Per-user JWT for MCP over HTTP
* **Decision:** The API/worker mints a short-lived HS256 JWT with the user id, persona and an encrypted marketplace token. The MCP
  servers verify it in ASGI middleware and scope every call to that tenant.

## ADR-5: Stream through Postgres rows, not in-memory queues
* **Decision:** The worker writes each LangGraph `updates` event to `run_events`, and the SSE endpoint tails those rows.
* **Consequence:** refreshes, multiple viewers and API restarts never lose progress or a pending approval. Polling adds about 0.5 s of latency.

## ADR-6: Independent fact checker for evaluation
* **Decision:** Unsupported claims are measured against the persona's ground-truth facts (`evals/checkers/fact_check.py`), not by
  `rag/verify.py`, so the system is not graded by its own verifier.

## ADR-7: GigSim clients use a seeded rule model by default
* **Context:** An LLM client per proposal is too slow on CPU.
* **Decision:** The rule model reads the same hidden preferences. An LLM mode (`GIGSIM_CLIENT_MODE=llm`) exists and falls back to rules.
* **Consequence:** reply rates measure fit to a transparent model. This is stated next to every reply-rate number.
