# Runbook

## Start

* Everything: `docker compose -f infra/docker-compose.yml up --build`
  (web+api :18000, GigSim :18081, Postgres :15432, Redis :16379, Qdrant :16333, Ollama :11434, Phoenix :16006).
* Local without Docker: `make dev`. This starts GigSim, the API and the worker; the web dev server runs on :15173.
* First run: `make seed-demo` creates the reviewer account (persona ai_ml) and analyses a few jobs.

## Schedules and rate limits

| Mode | Scout interval | Why |
|---|---|---|
| GigSim | 10 min | The simulator drips 5 jobs/min; this keeps the inbox fresh without hitting its 120 rpm limit. |
| Live Upwork | 180 min | Freelance jobs stay open for days, and three checks a day catch them well within the useful window. Each check is one `search_jobs` call per saved search (≤ 5) plus one `get_job` per new job, capped at 8 per run. This stays far from anything that looks like scraping. |

The per-user MCP limiter is 50 requests/min and waits politely instead of failing. The GigSim adapter retries 429 and 5xx
responses with exponential backoff and honours `Retry-After`.

## Degraded mode (marketplace down)

1. The ToolBox marks the server down. Nodes raise `MarketplaceUnavailable`, and the guard sets the job to `queued_degraded`.
2. The UI polls `/api/health/dependencies` and shows a red banner with the number of waiting jobs.
3. The worker `reconcile` cron (every 2 min) re-enqueues degraded jobs. Each graph continues from its last checkpoint.

## Crash recovery and exactly-once

* An approved run whose worker dies stays `running` in `runs`. `reconcile` re-enqueues it, and the graph resumes from the
  checkpoint (the `submit` node).
* Submit uses `idempotency_key = sha256(user, job, "submit")`. GigSim returns `idempotent_replay: true` on a retry, so
  Connects are spent once.

## Change request (policy v2)

Set `marketplace.policy_version: 2` in `agent/config.yaml` and restart the worker. No code change is needed
(see `docs/CHANGE_REQUEST.md`).

## Secrets

Secrets come only from the environment (`.env` locally, the host's secret store in production). OAuth tokens are
Fernet-encrypted in `credentials` and never logged.
