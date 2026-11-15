import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api, unwrap, type UserOut } from "../lib/client";

export function Loading({ label = "Loading" }: { label?: string }) {
  return <div className="state" role="status" aria-live="polite">{label}…</div>;
}
export function ErrorBox({ error }: { error: unknown }) {
  return <div className="banner bad" role="alert">{error instanceof Error ? error.message : String(error)}</div>;
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="state"><h2>{title}</h2>{children}</div>;
}

export function RiskBadge({ risk, flags }: { risk?: number | null; flags?: string[] | null }) {
  if (risk === null || risk === undefined) return <span className="badge b-muted">unscored</span>;
  const scam = (flags || []).filter((f) => f !== "prompt_injection");
  const cls = risk >= 0.6 || scam.length ? "b-bad" : risk >= 0.35 ? "b-warn" : "b-ok";
  const label = scam.length ? scam[0].replace(/_/g, " ") : risk >= 0.35 ? "check client" : "low risk";
  return (
    <span className="row" style={{ gap: 4 }}>
      <span className={`badge ${cls}`} title={`risk ${Math.round(risk * 100)}%`}>{label}</span>
      {(flags || []).includes("prompt_injection") && <span className="badge b-warn" title="Injected instructions detected and ignored">injection</span>}
    </span>
  );
}

const ACTION: Record<string, string> = { bid: "b-ok", watch: "b-warn", skip: "b-muted" };
export function ActionBadge({ status, decision }: { status: string; decision?: string | null }) {
  const label = status === "awaiting_approval" ? "awaiting approval" : status === "queued_degraded" ? "queued (marketplace down)" :
    decision ? decision : status.replace(/_/g, " ");
  const cls = status === "awaiting_approval" ? "b-info" : status === "queued_degraded" || status === "dead_letter" || status === "needs_attention" ? "b-bad" :
    ACTION[decision || ""] || "b-muted";
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function FitBar({ fit }: { fit?: number | null }) {
  const v = Math.max(0, Math.min(1, fit ?? 0));
  return (
    <div className="row" style={{ gap: 6 }} aria-label={`fit ${Math.round(v * 100)} percent`}>
      <div className="bar" style={{ width: 70 }}><span style={{ width: `${v * 100}%` }} /></div>
      <span className="muted">{fit === null || fit === undefined ? "—" : `${Math.round(v * 100)}%`}</span>
    </div>
  );
}

/** Polls the dependency health endpoint and shows a banner when the marketplace MCP server is unreachable. */
export function DegradedBanner() {
  const [h, setH] = useState<{ marketplace: string; queued_degraded: number; details?: Record<string, unknown> } | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await api.GET("/api/health/dependencies");
        if (alive && r.data) setH(r.data as never);
      } catch { /* api down is shown by page errors */ }
    };
    tick();
    const t = setInterval(tick, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!h || h.marketplace !== "down") return h && h.queued_degraded > 0 ?
    <div className="banner warn" role="status">Marketplace is back - {h.queued_degraded} queued job(s) are being retried.</div> : null;
  return (
    <div className="banner bad" role="alert" data-testid="degraded-banner">
      <strong>Marketplace unavailable.</strong> New work is queued and will resume automatically when it recovers.
      {h.queued_degraded ? ` ${h.queued_degraded} job(s) waiting.` : ""}
    </div>
  );
}

export function useMe() {
  const [me, setMe] = useState<UserOut | null | undefined>(undefined);
  useEffect(() => { api.GET("/api/me").then((r) => setMe(r.data ?? null)).catch(() => setMe(null)); }, []);
  return me;
}

export function Layout() {
  const me = useMe();
  const nav = useNavigate();
  useEffect(() => {
    if (me === null) nav("/login");
    else if (me && !me.onboarding_done) nav("/onboarding");
  }, [me, nav]);
  if (me === undefined) return <Loading />;
  const links: [string, string][] = [["/inbox", "Job inbox"], ["/pipeline", "Pipeline"], ["/messages", "Messages"],
    ["/runs", "Agent runs"], ["/analytics", "Analytics"], ["/settings", "Settings"]];
  return (
    <div className="shell">
      <nav className="nav" aria-label="Main">
        <div className="brand"><img src="/favicon.svg" width={24} height={24} alt="" /> BidPilot</div>
        {links.map(([to, label]) => <NavLink key={to} to={to}>{label}</NavLink>)}
        <div className="who">{me?.email}<br />persona: {me?.persona}<br />
          <button style={{ marginTop: 8 }} onClick={async () => { await api.POST("/api/auth/logout"); nav("/login"); }}>Sign out</button>
        </div>
      </nav>
      <main>
        <DegradedBanner />
        <Outlet />
      </main>
    </div>
  );
}

export async function loadOrThrow<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  return unwrap(await p);
}
