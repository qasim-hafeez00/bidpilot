# Architecture

```
Browser (React) --REST/SSE--> FastAPI --enqueue--> Arq worker (Redis) --runs--> LangGraph graphs
                                  |                                   |  checkpointer + store: Postgres
                                  '-- reads checkpoints / events -----'  MCP (stdio locally, Streamable HTTP + JWT in docker)
                                                                        |-- Portfolio MCP --> RAG (fastembed ONNX, BM25, Qdrant/numpy)
                                                                        |-- Marketplace MCP --> port --> GigSim REST | Upwork MCP (OAuth)
                                                                        '-- Workspace MCP --> calendar/email mock (SQLite)
```

Mermaid renderings of both graphs are generated from code by `python -m scripts.render_graphs` into `docs/images/`.

## Why each agent exists

| Agent | Responsibility | Why a separate node | Model |
|---|---|---|---|
| Scout | Saved searches on a schedule, dedup (job id + 5-gram Jaccard ≥ 0.8), queue | Runs in the worker, not per job | none |
| Job Analyst | `JobSpec` | Structured spec reused by the Writer and the UI | rules (+ small LLM, optional) |
| Risk Assessor | Client quality, scam lexicon, injection detection | Needs client-history tool; must run before any LLM sees the text | rules |
| Fit Matcher | Requirement → evidence matrix, fit score | Only reader of the portfolio; runs in parallel | retrieval + cross-encoder |
| Decision | skip / watch / bid | Join point; thresholds in config | rules |
| Pricing | Bid amount, fair band, Connects EV | Needs market statistics tool | rules |
| Writer | Cover letter + screening answers with `[E:id]` markers | Only node that needs the strongest model | strong tier |
| Claim verification | Remove unsupported claims | Grounding must happen before the Critic | cross-encoder + entity checks |
| Critic | Grounding, personalisation, length, answers, citations; ≤ 2 revisions | Quality failures loop back; policy failures do not | rules (+ LLM optional) |
| Compliance Guard | Policy pack from config; remove or block | Only node allowed to block | rules |
| Client Liaison | Intent, reply, interview slots | Separate conversation thread lifecycle | rules + LLM |

## State, trace, memory

* **State** (`agent/state.py`): per-thread, typed, with reducers wherever parallel branches write.
* **Trace**: the `trace` list in state, LangSmith or Phoenix spans, and the MCP audit log. One trace id runs from the UI
  request to the root `run_id` to MCP `trace_id` arguments to audit rows.
* **Memory** (`agent/memory/`): `style` and `outcome_insights` namespaces in the LangGraph store, written only by
  `promotion_rules.py`. It is viewable and deletable in Settings.

## ADRs

See `docs/adr/`.
