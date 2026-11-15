import { useState } from "react";

export type Claim = { text: string; label: string; evidence_id?: string | null; score?: number | null; missing?: string[]; evidence?: string };
export type Evidence = { evidence_id: string; title?: string; type?: string; snippet?: string; project_id?: string; date?: string; outcome?: string };

const LABEL: Record<string, string> = { supported: "supported", partly_supported: "partly supported", unsupported: "unsupported (removed)" };

/** Renders a draft with every claim underlined by verification status; hover or focus shows the evidence behind it. */
export function EvidenceText({ text, claims, evidence }: { text: string; claims: Claim[]; evidence: Evidence[] }) {
  const byId = new Map(evidence.map((e) => [e.evidence_id, e]));
  const sentences = text.split(/(?<=[.!?])\s+(?=[A-Z"'(])/);
  return (
    <p style={{ lineHeight: 1.7 }}>
      {sentences.map((s, i) => {
        const plain = s.replace(/\s*\[E:[^\]]+\]/g, "");
        const ids = [...s.matchAll(/\[E:([^\]]+)\]/g)].map((m) => m[1]);
        const c = claims.find((x) => x.text && plain.startsWith(x.text.slice(0, 40)));
        if (!c && !ids.length) return <span key={i}>{plain} </span>;
        const ev = byId.get(c?.evidence_id || ids[0]);
        return <ClaimSpan key={i} text={plain} claim={c} ev={ev} ids={ids} />;
      })}
    </p>
  );
}

function ClaimSpan({ text, claim, ev, ids }: { text: string; claim?: Claim; ev?: Evidence; ids: string[] }) {
  const [open, setOpen] = useState(false);
  const label = claim?.label || "cited";
  return (
    <span className={`claim ${label}`} tabIndex={0} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} aria-describedby={open ? "evidence-tip" : undefined}
      data-testid="claim">
      {text}{" "}
      {open && (
        <span className="tip" role="tooltip" id="evidence-tip">
          <strong>{LABEL[label] || label}</strong>{claim?.score !== undefined && claim?.score !== null ? ` · grounding ${Math.round((claim.score || 0) * 100)}%` : ""}
          <br />
          {ev ? (<><span className="mono">{ev.evidence_id}</span> · {ev.type} {ev.date ? `· ${ev.date}` : ""}<br />
            <em>{ev.title}</em><br />{(ev.snippet || claim?.evidence || "").slice(0, 320)}…</>)
            : <span className="mono">{ids.join(", ") || "no evidence id"}</span>}
          {claim?.missing?.length ? <><br /><span style={{ color: "var(--bad)" }}>Not found in evidence: {claim.missing.join(", ")}</span></> : null}
        </span>
      )}
    </span>
  );
}
