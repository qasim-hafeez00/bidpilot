# MCP tool inventory

All servers use the official MCP Python SDK (1.12.4) with Pydantic input schemas and declared output schemas
(`structured_output`). Annotations: RO = readOnlyHint, D = destructiveHint, I = idempotentHint, OW = openWorldHint.

| Tool | Server | R/W | Annotations | Auth | Used by (allowlist) |
|---|---|---|---|---|---|
| search_evidence(requirement, k, filters) | portfolio | read | RO, I | per-user JWT (HTTP) / env (stdio); tenant-scoped persona | fit_matcher, writer, critic, verifier, client_liaison |
| get_case_study(id) | portfolio | read | RO, I | same | writer, critic |
| list_skills(persona) | portfolio | read | RO, I | same | fit_matcher |
| resources `portfolio://case/{id}`, `portfolio://proposal/{id}`, `portfolio://cv/{persona}` | portfolio | read | — | same | hosts |
| prompts `answer_screening_question`, `fit_check`, `case_study_to_bullets` | portfolio | — | — | same | hosts |
| search_jobs(query, skills, posted_after, limit) | marketplace | read | RO, I, OW | per-user JWT carrying the encrypted GigSim/Upwork token | scout |
| get_job(job_id) | marketplace | read | RO, I, OW | same | intake, scout, client_liaison |
| get_client_history(client_id) | marketplace | read | RO, I, OW | same | risk_assessor |
| get_connects_balance() | marketplace | read | RO, I, OW | same | pricing, approval |
| get_market_stats(domain, kind) | marketplace | read | RO, I, OW | same | pricing |
| list_messages(thread_id) | marketplace | read | RO, I, OW | same | client_liaison, pipeline |
| list_events(after_id) / list_proposals() | marketplace | read | RO, I, OW | same | pipeline |
| create_proposal_draft(…, idempotency_key, dry_run) | marketplace | write | ¬RO, ¬D, I, OW | same | approval (dry_run only), submitter |
| submit_proposal(proposal_id, idempotency_key, dry_run) | marketplace | write (spends Connects) | ¬RO, D, I, OW | same | submitter (only after approval) |
| send_message(thread_id, text, idempotency_key, dry_run) | marketplace | write | ¬RO, D, I, OW | same | liaison_sender (only after approval) |
| get_free_slots(start_date, days, duration_min, timezone) | workspace | read | RO, I | per-user JWT | client_liaison |
| create_interview_hold(start, duration_min, title, idempotency_key) | workspace | write (tentative) | ¬RO, ¬D, I | same | liaison_sender |
| create_email_draft(to_label, subject, body, idempotency_key) | workspace | write (draft) | ¬RO, ¬D, I | same | liaison_sender |

Every marketplace call is rate limited per user (50/min, under GigSim's 120/min; the limiter waits rather than failing)
and appended to `data/processed/audit/*.jsonl`, plus the Postgres `audit_log` table when `AUDIT_TO_DB=1`. That table is
append-only, enforced by a trigger. Each audit row records the user, tool, masked arguments, result and trace id.

## Third-party servers

| Server | Why it is trusted (one line) |
|---|---|
| Upwork official MCP (`https://mcp.upwork.com/mcp`) | Operated by the marketplace itself, OAuth 2.1 with user consent, and every write is a draft the user confirms on Upwork. |
| GitHub MCP server (`github/github-mcp-server`) | Maintained by GitHub, scoped by a fine-grained read-only token, and used only to ingest the user's own repositories. |
