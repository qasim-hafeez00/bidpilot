import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, fmtMoney, pct, unwrap, type JobDetail, type JobRow } from "../lib/client";
import { ActionBadge, Empty, ErrorBox, FitBar, Loading, RiskBadge } from "../components/common";
import { RunTimeline } from "../components/RunTimeline";

export function Inbox() {
  const nav = useNavigate();
  const [rows, setRows] = useState<JobRow[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [minFit, setMinFit] = useState(0);
  const load = useCallback(async () => {
    try {
      setRows(unwrap(await api.GET("/api/jobs", { params: { query: { status: status || undefined, q: q || undefined, min_fit: minFit } } })));
      setErr(null);
    } catch (e) { setErr(e); }
  }, [status, q, minFit]);
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, [load]);
  const skip = async (id: string) => { await api.POST("/api/jobs/{job_id}/skip", { params: { path: { job_id: id } } }); load(); };
  return (
    <>
      <div className="row"><div><h1>Job inbox</h1><p className="sub">New jobs ranked by fit, with risk badges, the recommended action, price and Connects cost.</p></div>
        <div className="spacer" /><button onClick={async () => { await api.POST("/api/jobs/scout"); setTimeout(load, 4000); }}>Scout now</button></div>
      <div className="card row" style={{ marginBottom: 16 }}>
        <label style={{ minWidth: 180 }}>Status<select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
          <option value="">All</option><option value="awaiting_approval">Awaiting approval</option><option value="watch">Watch</option>
          <option value="skipped">Skipped</option><option value="submitted">Submitted</option><option value="queued">Queued</option>
          <option value="queued_degraded">Queued (degraded)</option></select></label>
        <label style={{ flex: 1, minWidth: 180 }}>Search title<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. dashboard" /></label>
        <label style={{ width: 140 }}>Min fit<input type="number" min={0} max={1} step={0.05} value={minFit} onChange={(e) => setMinFit(+e.target.value)} /></label>
      </div>
      {err ? <ErrorBox error={err} /> : null}
      {rows === null ? <Loading label="Loading jobs" /> : rows.length === 0 ? (
        <Empty title="No jobs yet">Scouting runs every few minutes for your saved searches. Click “Scout now” to run it immediately.</Empty>
      ) : (
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table data-testid="inbox-table">
            <thead><tr><th>Job</th><th>Fit</th><th>Risk</th><th>Action</th><th className="hide-sm">Price</th><th className="hide-sm">Connects</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.job_id} className="click" onClick={() => nav(`/jobs/${r.job_id}`)} tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && nav(`/jobs/${r.job_id}`)} data-testid="job-row">
                  <td><strong>{r.title || r.job_id}</strong><div className="muted">{r.category} · {r.job_id}</div></td>
                  <td><FitBar fit={r.fit} /></td>
                  <td><RiskBadge risk={r.risk} flags={r.risk_flags} /></td>
                  <td><ActionBadge status={r.status} decision={r.decision} /></td>
                  <td className="hide-sm">{fmtMoney(r.price as never)}</td>
                  <td className="hide-sm">{r.connects_cost ?? "—"}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {r.status === "awaiting_approval" ? <Link to={`/studio/${r.job_id}`}>Review</Link> :
                      !["skipped_by_user", "submitted"].includes(r.status) ? <button onClick={() => skip(r.job_id)} aria-label={`Skip ${r.title}`}>Skip</button> : null}
                  </td>
                </tr>))}
            </tbody>
          </table>
        </div>)}
    </>
  );
}

export function JobDetailPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [d, setD] = useState<JobDetail | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setD(unwrap(await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } }))); } catch (e) { setErr(e); }
  }, [id]);
  useEffect(() => { load(); }, [load]);
  if (err) return <ErrorBox error={err} />;
  if (!d) return <Loading />;
  const job = d.job as Record<string, any>;
  const fit = d.fit_report as Record<string, any> | null;
  const risk = d.risk_report as Record<string, any> | null;
  const spec = d.job_spec as Record<string, any> | null;
  const price = d.price_quote as Record<string, any> | null;
  const analyze = async (force: boolean) => {
    const r = unwrap(await api.POST("/api/jobs/{job_id}/analyze", { params: { path: { job_id: id }, query: { force_bid: force } } }));
    setRunId(r.run_id);
  };
  return (
    <>
      <div className="row"><div><h1>{job.title}</h1><p className="sub">{d.job_id} · <ActionBadge status={d.status} decision={(d.decision as any)?.action} /></p></div>
        <div className="spacer" />
        {d.status === "awaiting_approval" && <button className="primary" onClick={() => nav(`/studio/${id}`)}>Open proposal studio</button>}
        {["watch", "skipped"].includes(d.status) && <button onClick={() => analyze(true)}>Bid anyway</button>}
        <button onClick={() => analyze(false)}>Re-analyze</button>
        {d.trace_url && <a className="btn" href={d.trace_url} target="_blank" rel="noreferrer">Trace</a>}
      </div>
      {runId && <div className="card" style={{ marginBottom: 16 }}><h2>Live run</h2><RunTimeline runId={runId} onDone={() => load()} /></div>}
      {d.attention_reason && <div className="banner warn">{d.attention_reason}</div>}
      <div className="grid g2">
        <div className="card"><h2>Bid or skip</h2>
          <p><ActionBadge status={d.status} decision={(d.decision as any)?.action} /></p>
          <ul>{((d.decision as any)?.reasons || []).map((r: string, i: number) => <li key={i}>{r}</li>)}</ul></div>
        <div className="card"><h2>Risk report</h2>
          <RiskBadge risk={risk?.score} flags={risk?.flags} />
          <p className="muted">{risk?.explanation}</p>
          {risk?.injection_spans?.length ? <><h3>Ignored injected text</h3>{risk.injection_spans.map((s: string, i: number) => <pre key={i} className="mono">{s}</pre>)}</> : null}</div>
        <div className="card"><h2>JobSpec</h2>
          <p><strong>Core skills:</strong> {(spec?.core_skills || []).join(", ") || "—"}<br /><strong>All skills:</strong> {(spec?.required_skills || []).join(", ")}</p>
          <p><strong>Budget:</strong> {spec?.budget_type} {spec?.budget_min ?? ""}{spec?.budget_max && spec?.budget_max !== spec?.budget_min ? `–${spec.budget_max}` : ""} · <strong>Level:</strong> {spec?.experience_level || "—"}</p>
          {spec?.deliverables?.length ? <><h3>Deliverables</h3><ul>{spec.deliverables.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></> : null}
          {spec?.screening_questions?.length ? <><h3>Screening questions</h3><ul>{spec.screening_questions.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></> : null}</div>
        <div className="card"><h2>Price rationale</h2>
          {price ? <><p className="stat">{fmtMoney(price as never)}</p><p className="muted">{price.rationale}</p>
            <p>Fair band ${price.band?.[0]}–${price.band?.[1]} · Connects {price.connects_cost} ({price.connects_worth_it ? "worth it" : "not worth it"})</p></>
            : <p className="muted">Priced only for jobs recommended for a bid.</p>}</div>
      </div>
      <div className="card" style={{ marginTop: 16, overflowX: "auto" }}>
        <h2>Requirement → evidence matrix <span className="muted">fit {pct(fit?.score)}</span></h2>
        <table data-testid="evidence-matrix"><thead><tr><th>Requirement</th><th>Strength</th><th>Portfolio evidence</th></tr></thead>
          <tbody>{(fit?.matrix || []).map((m: any, i: number) => (
            <tr key={i}><td>{m.skill ? <strong>{m.skill}{m.core ? " (core)" : ""}: </strong> : null}{m.requirement}</td>
              <td><span className={`badge ${m.strength === "strong" ? "b-ok" : m.strength === "partial" ? "b-warn" : "b-bad"}`}>{m.strength}</span></td>
              <td className="mono">{(m.evidence_ids || []).join(", ") || "none - will not be claimed"}</td></tr>))}</tbody></table>
      </div>
      <div className="card" style={{ marginTop: 16 }}><h2>Job post <span className="muted">(untrusted text)</span></h2><pre>{job.description}</pre></div>
      <div className="card" style={{ marginTop: 16 }}><h2>Runs</h2>
        <ul>{d.runs.map((r: any) => <li key={r.run_id}><Link to={`/runs/${r.run_id}`}>{r.started_at?.slice(0, 19)}</Link> · {r.status} · {r.latency_s ? `${r.latency_s.toFixed(1)}s` : ""}</li>)}</ul></div>
    </>
  );
}
