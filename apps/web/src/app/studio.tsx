import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, stripMarkers, unwrap, type ProposalOut } from "../lib/client";
import { Empty, ErrorBox, Loading, RiskBadge } from "../components/common";
import { ApprovalPanel } from "../components/ApprovalPanel";
import { EvidenceText, type Claim, type Evidence } from "../components/EvidenceHover";
import { RunTimeline } from "../components/RunTimeline";

/** Proposal studio: evidence on hover, Critic + Compliance inline, regenerate one paragraph, approve / edit / reject. */
export function Studio() {
  const { id = "" } = useParams();
  const [p, setP] = useState<ProposalOut | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [text, setText] = useState("");
  const [original, setOriginal] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [regen, setRegen] = useState<{ idx: number; busy: boolean; note?: string } | null>(null);
  const load = useCallback(async () => {
    try {
      const out = unwrap(await api.GET("/api/proposals/{job_id}", { params: { path: { job_id: id } } }));
      setP(out);
      const draft = (out.pending as any)?.draft?.cover_letter ?? out.drafts.at(-1)?.cover_letter ?? "";
      setOriginal(stripMarkers(draft)); setText(stripMarkers(draft));
    } catch (e) { setErr(e); }
  }, [id]);
  useEffect(() => { load(); }, [load]);
  if (err) return <ErrorBox error={err} />;
  if (!p) return <Loading label="Loading proposal" />;
  const pend = p.pending as any;
  if (!pend) {
    return (
      <>
        <h1>Proposal studio</h1>
        {runId && <div className="card"><RunTimeline runId={runId} onDone={() => load()} /></div>}
        {p.submission ? <div className="card" data-testid="submitted"><h2>Submitted</h2>
          <p>Proposal <span className="mono">{(p.submission as any).proposal_id}</span> - status {(p.submission as any).status}
            {(p.submission as any).idempotent_replay ? " (idempotent replay: not submitted twice)" : ""}.</p>
          <p>Connects spent: {(p.submission as any).connects_spent}</p></div>
          : <Empty title={p.status === "rejected" ? "Rejected" : "Nothing waiting for approval"}>
              {p.attention_reason || "This job has no pending proposal."} <Link to={`/jobs/${id}`}>Open job</Link></Empty>}
      </>
    );
  }
  const claims: Claim[] = pend.claims || [];
  const evidence: Evidence[] = pend.evidence || [];
  const crit = pend.critique || {};
  const comp = pend.compliance || {};
  const ver = pend.verification || {};
  const edited = text.trim() !== original.trim();
  const paragraphs = text.split(/\n\s*\n/);
  const decide = async (action: "approve" | "edit" | "reject", reason?: string) => {
    setBusy(true);
    try {
      const r = unwrap(await api.POST("/api/proposals/{job_id}/decision", { params: { path: { job_id: id } },
        body: { action, reason: reason ?? null, edited_text: action === "edit" ? text : null } }));
      setRunId(r.run_id); setP({ ...p, pending: null });
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const regenerate = async (idx: number) => {
    setRegen({ idx, busy: true });
    try {
      const r = (await api.POST("/api/proposals/{job_id}/regenerate", { params: { path: { job_id: id } },
        body: { paragraph: paragraphs[idx], instruction: "more specific to the client's problem" } })).data as any;
      if (r?.paragraph) { const next = [...paragraphs]; next[idx] = stripMarkers(r.paragraph); setText(next.join("\n\n")); setEditing(true); }
      setRegen({ idx, busy: false, note: r?.removed_claims?.length ? `Removed ${r.removed_claims.length} unsupported claim(s)` : "Regenerated" });
    } catch (e) { setRegen({ idx, busy: false, note: String(e) }); }
  };
  return (
    <>
      <div className="row"><div><h1>Proposal studio</h1><p className="sub">{pend.title}</p></div><div className="spacer" />
        <RiskBadge risk={pend.risk_report?.score} flags={pend.risk_report?.flags} /></div>
      <div className="grid g2" style={{ alignItems: "start" }}>
        <div className="grid">
          <div className="card">
            <div className="row"><h2>Cover letter <span className="muted">v{pend.draft?.version} · {pend.draft?.mode}</span></h2><div className="spacer" />
              <button onClick={() => setEditing(!editing)} data-testid="toggle-edit">{editing ? "Show evidence view" : "Edit"}</button></div>
            {editing ? (
              <>
                <textarea value={text} onChange={(e) => setText(e.target.value)} aria-label="Proposal text" data-testid="editor" />
                <div className="row" style={{ marginTop: 8 }}>
                  {paragraphs.map((_, i) => <button key={i} disabled={regen?.busy} onClick={() => regenerate(i)}>Regenerate paragraph {i + 1}</button>)}
                  {regen && <span className="muted">{regen.busy ? "Regenerating…" : regen.note}</span>}
                </div>
              </>
            ) : <EvidenceText text={pend.draft?.cover_letter || ""} claims={claims} evidence={evidence} />}
            <p className="muted">Underline: <span className="claim supported">supported</span> · <span className="claim partly_supported">partly</span> - hover or focus a sentence to see its evidence.</p>
            {pend.draft?.screening_answers?.length ? <><h3>Screening answers</h3><ol>{pend.draft.screening_answers.map((a: string, i: number) => <li key={i}>{stripMarkers(a)}</li>)}</ol></> : null}
          </div>
          <div className="card"><h2>Critic</h2>
            {crit.passed ? <span className="badge b-ok">passed</span> : <span className="badge b-warn">unresolved after max revisions</span>}
            <ul>{(crit.issues || []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
            <p className="muted">Claims: {ver.before?.claims ?? 0} before verification ({ver.before?.unsupported ?? 0} unsupported) → {ver.after?.unsupported ?? 0} unsupported after.</p>
            {ver.removed?.length ? <><h3>Removed by claim verification</h3><ul>{ver.removed.map((x: string, i: number) => <li key={i}><s>{x}</s></li>)}</ul></> : null}
          </div>
          <div className="card"><h2>Compliance Guard</h2>
            <span className={`badge ${comp.status === "pass" ? "b-ok" : comp.status === "fixed" ? "b-warn" : "b-bad"}`}>{comp.status}</span>
            <ul>{(comp.violations || []).map((v: any, i: number) => <li key={i}><strong>{v.rule}</strong>: {v.message} <s className="muted">{v.sentence}</s></li>)}</ul>
            {pend.notes && <div className="banner warn">{pend.notes}</div>}
          </div>
        </div>
        <div className="grid">
          <ApprovalPanel dryRun={pend.dry_run} edited={edited} busy={busy} onDecide={decide} />
          {runId && <div className="card"><h2>Progress</h2><RunTimeline runId={runId} onDone={() => load()} /></div>}
          <div className="card"><h2>Price</h2><p><strong>${pend.price_quote?.amount}</strong> {pend.price_quote?.bid_type}</p><p className="muted">{pend.price_quote?.rationale}</p></div>
          <div className="card"><h2>Evidence ({evidence.length})</h2>
            {evidence.map((e) => <div key={e.evidence_id} style={{ marginBottom: 8 }}><span className="mono">{e.evidence_id}</span> <span className="badge b-muted">{e.type}</span><br /><span className="muted">{e.title}</span></div>)}</div>
        </div>
      </div>
    </>
  );
}
