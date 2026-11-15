import { useRunStream } from "../lib/useRunStream";

const NICE: Record<string, string> = {
  intake: "Scout hand-off", analyst: "Job Analyst", risk_assessor: "Risk Assessor", fit_matcher: "Fit Matcher", decide: "Decision",
  pricing: "Pricing Strategist", writer: "Proposal Writer", verifier: "Claim verification", critic: "Critic", compliance: "Compliance Guard",
  prepare_approval: "Dry-run preview", approval: "Your approval", submit: "Submit (idempotent)", __interrupt__: "Waiting for your approval",
  read_messages: "Read messages", classify: "Classify intent", find_slots: "Calendar slots", draft_reply: "Draft reply", approve: "Your approval",
  send: "Send", __end__: "Finished", error: "Error",
};

/** Live node-by-node progress of one run (SSE). */
export function RunTimeline({ runId, onDone }: { runId: string; onDone?: (status?: string) => void }) {
  const { events, done, error } = useRunStream(runId);
  if (done && onDone) setTimeout(() => onDone(done.status), 0);
  return (
    <div aria-live="polite">
      {!events.length && !done && <p className="muted">Queued - waiting for a worker…</p>}
      <ol className="timeline" data-testid="run-timeline">
        {events.map((e, i) => (
          <li key={i}>
            <strong>{NICE[e.node] || e.node}</strong>{" "}
            {e.status && <span className="badge b-muted">{e.status}</span>}{" "}
            {e.trace && <span className="muted mono">{summarize(e.trace)}</span>}
            {e.attention && <div style={{ color: "var(--bad)" }}>{e.attention}</div>}
            {e.error && <div style={{ color: "var(--bad)" }}>{e.error}</div>}
            {e.trace_url && <div><a href={e.trace_url} target="_blank" rel="noreferrer">Open full trace</a></div>}
          </li>
        ))}
      </ol>
      {!done && events.length > 0 && <p className="muted">Running… (live)</p>}
      {error && !done && <p className="muted">{error}</p>}
    </div>
  );
}

function summarize(t: Record<string, unknown>): string {
  const keep = ["action", "score", "flags", "tool", "calls", "amount", "passed", "issues", "status", "violations", "intent", "mode", "words", "removed", "replay"];
  return keep.filter((k) => t[k] !== undefined).map((k) => `${k}=${JSON.stringify(t[k]).slice(0, 80)}`).join(" ");
}
