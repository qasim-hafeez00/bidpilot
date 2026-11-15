import { useState } from "react";

type DryRun = { payload?: { bid_amount?: number; bid_type?: string; cover_letter?: string }; connects_cost?: number; balance?: number;
  balance_after?: number; marketplace?: string } | null | undefined;

/** Approve / edit / reject with a dry-run preview of exactly what will be sent and what it costs. */
export function ApprovalPanel({ dryRun, edited, busy, onDecide }: {
  dryRun: DryRun; edited: boolean; busy: boolean;
  onDecide: (action: "approve" | "edit" | "reject", reason?: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  return (
    <div className="card" aria-labelledby="approve-h">
      <h2 id="approve-h">Approve before anything is sent</h2>
      {dryRun ? (
        <table data-testid="dry-run">
          <tbody>
            <tr><th>Marketplace</th><td>{dryRun.marketplace}</td></tr>
            <tr><th>Bid</th><td>${dryRun.payload?.bid_amount}{dryRun.payload?.bid_type === "hourly" ? "/h" : " fixed"}</td></tr>
            <tr><th>Connects</th><td>{dryRun.connects_cost} (balance {dryRun.balance} → {dryRun.balance_after})</td></tr>
          </tbody>
        </table>
      ) : <p className="muted">No dry-run preview available.</p>}
      <p className="muted">Nothing is submitted until you click a button below. Edits are re-checked by Compliance.</p>
      {!rejecting ? (
        <div className="row">
          <button className="primary" disabled={busy} onClick={() => onDecide(edited ? "edit" : "approve")} data-testid="approve">
            {edited ? "Approve with my edits" : "Approve & submit"}
          </button>
          <button className="danger" disabled={busy} onClick={() => setRejecting(true)} data-testid="reject">Reject…</button>
        </div>
      ) : (
        <div className="grid">
          <label>Why are you rejecting it? (helps BidPilot learn)
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. too generic, wrong price" data-testid="reject-reason" autoFocus />
          </label>
          <div className="row">
            <button className="danger" disabled={busy || reason.trim().length < 3} onClick={() => onDecide("reject", reason)} data-testid="confirm-reject">Reject proposal</button>
            <button onClick={() => setRejecting(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
