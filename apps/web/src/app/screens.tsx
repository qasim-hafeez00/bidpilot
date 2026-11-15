import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, unwrap, type Settings } from "../lib/client";
import { Empty, ErrorBox, Loading } from "../components/common";
import { RunTimeline } from "../components/RunTimeline";

const STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"];

export function Pipeline() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    const load = () => api.GET("/api/pipeline").then((r) => setRows(unwrap(r) as any[])).catch(setErr);
    load(); const t = setInterval(load, 10000); return () => clearInterval(t);
  }, []);
  if (err) return <ErrorBox error={err} />;
  if (!rows) return <Loading />;
  return (
    <>
      <h1>Pipeline</h1><p className="sub">Cards move automatically as marketplace events arrive.</p>
      {rows.length === 0 ? <Empty title="No proposals yet">Approve a proposal in the studio to start your pipeline.</Empty> : (
        <div className="kanban" data-testid="kanban">
          {STAGES.map((s) => {
            const items = rows.filter((r) => r.stage === s);
            return (<section className="col" key={s} aria-label={s}><h3>{s}<span className="badge b-muted">{items.length}</span></h3>
              {items.map((r) => <div className="kcard" key={r.proposal_id}><Link to={`/jobs/${r.job_id}`}>{r.title || r.job_id}</Link>
                <div className="muted">{r.category} · {r.connects_spent} Connects</div>
                {r.thread_id && <Link to={`/messages/${r.thread_id}`}>Conversation</Link>}</div>)}</section>);
          })}
        </div>)}
    </>
  );
}

export function Messages() {
  const { threadId } = useParams();
  const nav = useNavigate();
  const [threads, setThreads] = useState<any[] | null>(null);
  const [t, setT] = useState<any | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [text, setText] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const loadThread = useCallback(async () => {
    if (!threadId) return;
    try { const out = unwrap(await api.GET("/api/messages/{thread_id}", { params: { path: { thread_id: threadId } } })); setT(out);
      setText((out.pending as any)?.reply?.text || ""); } catch (e) { setErr(e); }
  }, [threadId]);
  useEffect(() => { api.GET("/api/messages").then((r) => setThreads(unwrap(r))).catch(setErr); }, [runId]);
  useEffect(() => { loadThread(); }, [loadThread]);
  const decide = async (action: "approve" | "edit" | "reject") => {
    const r = unwrap(await api.POST("/api/messages/{thread_id}/decision", { params: { path: { thread_id: threadId! } },
      body: { action, edited_text: action === "edit" ? text : null, reason: action === "reject" ? reason : null } }));
    setRunId(r.run_id);
  };
  const pend = t?.pending;
  return (
    <>
      <h1>Messages</h1><p className="sub">Client threads with suggested replies and interview slots. Nothing is sent until you approve.</p>
      {err ? <ErrorBox error={err} /> : null}
      <div className="grid g2" style={{ gridTemplateColumns: "minmax(220px, 1fr) 2fr", alignItems: "start" }}>
        <div className="card" style={{ padding: 8 }}>
          {threads === null ? <Loading /> : threads.length === 0 ? <Empty title="No conversations">Client replies appear here.</Empty> :
            threads.map((th) => (
              <button key={th.thread_id} onClick={() => nav(`/messages/${th.thread_id}`)} style={{ display: "block", width: "100%", textAlign: "left", marginBottom: 6,
                background: th.thread_id === threadId ? "var(--info-bg)" : undefined }} data-testid="thread">
                <strong>{th.title || th.thread_id}</strong><br /><span className="muted">{th.intent || "new"} · {th.status}</span></button>))}
        </div>
        <div className="grid">
          {!threadId ? <Empty title="Pick a conversation" /> : !t ? <Loading /> : (
            <>
              <div className="card">{t.messages.map((m: any) => <div key={m.message_id} className={`msg ${m.sender}`}><span className="muted">{m.sender}</span><br />{m.text}</div>)}</div>
              {runId && <div className="card"><RunTimeline runId={runId} onDone={() => { setRunId(null); loadThread(); }} /></div>}
              {pend ? (
                <div className="card" data-testid="reply-approval">
                  <h2>Suggested reply <span className="badge b-info">{pend.intent?.intent}</span></h2>
                  {pend.intent?.intent === "scam_signal" && <div className="banner bad">Scam signal: the client asked to move off-platform or for unpaid work. The reply declines politely.</div>}
                  {pend.slots?.length ? <p className="muted">Interview slots: {pend.slots.map((s: any) => s.label).join("; ")}</p> : null}
                  <textarea style={{ minHeight: 120 }} value={text} onChange={(e) => setText(e.target.value)} aria-label="Reply text" />
                  <div className="row" style={{ marginTop: 8 }}>
                    <button className="primary" onClick={() => decide(text !== pend.reply?.text ? "edit" : "approve")} data-testid="approve-reply">Approve & send</button>
                    <input style={{ maxWidth: 220 }} placeholder="Reason to reject" value={reason} onChange={(e) => setReason(e.target.value)} />
                    <button className="danger" disabled={reason.length < 3} onClick={() => decide("reject")}>Reject</button>
                  </div>
                </div>
              ) : (
                <div className="card row"><span className="muted">Status: {t.status}</span><div className="spacer" />
                  <button onClick={async () => setRunId(unwrap(await api.POST("/api/messages/{thread_id}/draft", { params: { path: { thread_id: threadId } } })).run_id)}>Draft a reply</button></div>)}
            </>)}
        </div>
      </div>
    </>
  );
}

export function Runs() {
  const { id } = useParams();
  const [runs, setRuns] = useState<any[] | null>(null);
  const [run, setRun] = useState<any | null>(null);
  useEffect(() => { api.GET("/api/runs").then((r) => setRuns(r.data as any[])); }, [id]);
  useEffect(() => { if (id) api.GET("/api/runs/{run_id}", { params: { path: { run_id: id } } }).then((r) => setRun(r.data)); }, [id]);
  return (
    <>
      <h1>Agent runs</h1><p className="sub">Live node-by-node progress streamed from LangGraph, with a link to the full trace.</p>
      <div className="grid g2" style={{ alignItems: "start" }}>
        <div className="card" style={{ overflowX: "auto" }}>
          {!runs ? <Loading /> : runs.length === 0 ? <Empty title="No runs yet" /> : (
            <table><thead><tr><th>Started</th><th>Kind</th><th>Status</th><th className="hide-sm">Latency</th><th className="hide-sm">Tokens</th></tr></thead>
              <tbody>{runs.map((r) => <tr key={r.run_id}><td><Link to={`/runs/${r.run_id}`}>{String(r.started_at).slice(5, 19)}</Link><div className="muted mono">{r.job_id}</div></td>
                <td>{r.kind}</td><td>{r.status}</td><td className="hide-sm">{r.latency_s ? `${r.latency_s.toFixed(1)}s` : "—"}</td><td className="hide-sm">{(r.tokens_in || 0) + (r.tokens_out || 0)}</td></tr>)}</tbody></table>)}
        </div>
        <div className="card">{!id ? <Empty title="Select a run" /> : <>
          <h2>Run {id.slice(0, 8)} {run?.trace_url && <a href={run.trace_url} target="_blank" rel="noreferrer">· full trace</a>}</h2>
          <p className="muted">trace id <span className="mono">{run?.trace_id}</span></p>
          <RunTimeline runId={id} /></>}</div>
      </div>
    </>
  );
}

export function Analytics() {
  const [a, setA] = useState<any | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.GET("/api/analytics").then((r) => setA(unwrap(r))).catch(setErr); }, []);
  if (err) return <ErrorBox error={err} />;
  if (!a) return <Loading />;
  const rate = (r: any) => (r.submitted ? `${Math.round((100 * r.replied) / r.submitted)}%` : "—");
  const cl = a.proposal_cost_latency || {};
  return (
    <>
      <h1>Analytics</h1><p className="sub">Reply and hire rate by category, Connects spent versus outcomes, cost and latency per proposal.</p>
      <div className="grid g3">
        <div className="card"><div className="muted">Proposals (runs)</div><div className="stat">{cl.runs ?? 0}</div></div>
        <div className="card"><div className="muted">p95 latency / proposal</div><div className="stat">{cl.p95 ? `${Number(cl.p95).toFixed(0)}s` : "—"}</div></div>
        <div className="card"><div className="muted">Cost / proposal</div><div className="stat">${cl.runs ? (Number(cl.usd || 0) / cl.runs).toFixed(4) : "0"}</div><div className="muted">~{Math.round(cl.tokens || 0)} tokens</div></div>
      </div>
      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card"><h2>By category</h2><table><thead><tr><th>Category</th><th>Sent</th><th>Reply</th><th>Hired</th><th>Connects</th></tr></thead>
          <tbody>{a.by_category.map((r: any) => <tr key={r.category}><td>{r.category}</td><td>{r.submitted}</td><td>{rate(r)}</td><td>{r.hired}</td><td>{r.connects}</td></tr>)}</tbody></table></div>
        <div className="card"><h2>By opening style</h2><table><thead><tr><th>Style</th><th>Sent</th><th>Reply rate</th></tr></thead>
          <tbody>{a.by_opening_style.map((r: any) => <tr key={r.style}><td>{r.style}</td><td>{r.submitted}</td><td>{rate(r)}</td></tr>)}</tbody></table></div>
        <div className="card"><h2>Top rejection reasons</h2>{a.top_rejection_reasons.length ? <ol>{a.top_rejection_reasons.map((r: any) => <li key={r.reason}>{r.reason} ({r.n})</li>)}</ol> : <p className="muted">None yet.</p>}</div>
        <div className="card"><h2>Job funnel</h2><ul>{a.funnel.map((r: any) => <li key={r.status}>{r.status}: {r.n}</li>)}</ul></div>
      </div>
    </>
  );
}

export function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [mem, setMem] = useState<any[]>([]);
  const [acc, setAcc] = useState<any[]>([]);
  const [saved, setSaved] = useState(false);
  const loadMem = () => api.GET("/api/memory").then((r) => setMem((r.data as any[]) || []));
  useEffect(() => {
    api.GET("/api/me").then((r) => setS(r.data?.settings ?? null));
    api.GET("/api/accounts").then((r) => setAcc(((r.data as any)?.connected) || []));
    loadMem();
  }, []);
  if (!s) return <Loading />;
  const save = async () => { await api.PUT("/api/settings", { body: s }); setSaved(true); setTimeout(() => setSaved(false), 2000); };
  return (
    <>
      <h1>Settings</h1><p className="sub">Autonomy, budgets, saved searches, connected accounts and what BidPilot has learned.</p>
      <div className="grid g2" style={{ alignItems: "start" }}>
        <div className="card grid">
          <h2>Autonomy & budgets</h2>
          <label>Autonomy<select value={s.autonomy} onChange={(e) => setS({ ...s, autonomy: e.target.value as Settings["autonomy"] })}>
            <option value="suggest">Suggest only (I decide every job)</option><option value="auto_skip_low_fit">Auto-skip low-fit jobs (never auto-send)</option></select></label>
          <label>Hourly floor ($)<input type="number" value={s.hourly_floor} onChange={(e) => setS({ ...s, hourly_floor: +e.target.value })} /></label>
          <label>Minimum fixed price ($)<input type="number" value={s.min_fixed} onChange={(e) => setS({ ...s, min_fixed: +e.target.value })} /></label>
          <label>Weekly Connects budget<input type="number" value={s.weekly_connects_budget} onChange={(e) => setS({ ...s, weekly_connects_budget: +e.target.value })} /></label>
          <label>Saved searches (one per line)<textarea style={{ minHeight: 90 }} value={(s.saved_searches || []).map((x) => x.query).join("\n")}
            onChange={(e) => setS({ ...s, saved_searches: e.target.value.split("\n").filter(Boolean).map((query) => ({ query, skills: [], limit: 20 })) })} /></label>
          <div className="row"><button className="primary" onClick={save}>Save</button>{saved && <span className="badge b-ok">saved</span>}</div>
        </div>
        <div className="grid">
          <div className="card"><h2>Connected accounts</h2>
            <ul>{acc.map((a) => <li key={a.provider}>{a.provider} · connected {String(a.updated_at).slice(0, 10)}</li>)}</ul>
            <button onClick={async () => { const r = await api.GET("/api/auth/upwork/start"); const u = (r.data as any)?.authorize_url; if (u) window.location.href = u; else alert("Upwork OAuth unavailable"); }}>Connect Upwork (OAuth)</button></div>
          <div className="card" data-testid="memory"><h2>What BidPilot has learned</h2>
            <p className="muted">Only patterns that passed a promotion rule (e.g. seen in 3 of your last 5 edits). Delete anything you disagree with.</p>
            {mem.length === 0 ? <p className="muted">Nothing learned yet.</p> : <ul>{mem.map((m) => (
              <li key={m.namespace + m.key} style={{ marginBottom: 6 }}><span className="badge b-info">{m.namespace}</span> {m.rule || m.insight} <span className="muted">{m.support}</span>{" "}
                <button onClick={async () => { await api.DELETE("/api/memory/{namespace}/{key}", { params: { path: { namespace: m.namespace, key: m.key } } }); loadMem(); }} aria-label={`Forget ${m.key}`}>Forget</button></li>))}</ul>}
          </div>
        </div>
      </div>
    </>
  );
}
