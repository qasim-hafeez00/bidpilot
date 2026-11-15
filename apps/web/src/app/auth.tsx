import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, unwrap } from "../lib/client";
import { ErrorBox } from "../components/common";

export function Login() {
  const nav = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      const r = mode === "login" ? await api.POST("/api/auth/login", { body: { email, password } })
        : await api.POST("/api/auth/register", { body: { email, password } });
      const out = unwrap(r);
      nav(out.user.onboarding_done ? "/inbox" : "/onboarding");
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <main style={{ maxWidth: 420, margin: "8vh auto" }}>
      <div className="card">
        <div className="brand" style={{ marginLeft: 0 }}><img src="/favicon.svg" width={28} height={28} alt="" /> BidPilot</div>
        <p className="sub">Your multi-agent freelance copilot. It finds jobs, flags scams and drafts proposals backed by your own portfolio. Nothing is sent without your approval.</p>
        {err ? <ErrorBox error={err} /> : null}
        <form className="grid" onSubmit={submit}>
          <label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" data-testid="email" /></label>
          <label>Password<input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"} data-testid="password" /></label>
          <button className="primary" disabled={busy} data-testid="submit">{mode === "login" ? "Sign in" : "Create account"}</button>
        </form>
        <p className="muted" style={{ marginTop: 12 }}>
          {mode === "login" ? "New here? " : "Have an account? "}
          <button className="btn" onClick={() => setMode(mode === "login" ? "register" : "login")} data-testid="toggle-mode">
            {mode === "login" ? "Create an account" : "Sign in"}
          </button>
        </p>
      </div>
    </main>
  );
}

const DEFAULTS: Record<string, { floor: number; min: number; searches: string[] }> = {
  ai_ml: { floor: 34, min: 300, searches: ["machine learning python", "llm chatbot rag", "computer vision"] },
  fullstack: { floor: 30, min: 250, searches: ["react node full stack", "django api", "next.js typescript"] },
  data_analyst: { floor: 22, min: 150, searches: ["power bi dashboard", "sql data analysis", "tableau excel"] },
  own: { floor: 25, min: 200, searches: ["python"] },
};

export function Onboarding() {
  const nav = useNavigate();
  const [persona, setPersona] = useState<"ai_ml" | "fullstack" | "data_analyst" | "own">("ai_ml");
  const [market, setMarket] = useState<"gigsim" | "upwork_live">("gigsim");
  const [floor, setFloor] = useState(DEFAULTS.ai_ml.floor);
  const [minFixed, setMinFixed] = useState(DEFAULTS.ai_ml.min);
  const [budget, setBudget] = useState(80);
  const [searches, setSearches] = useState(DEFAULTS.ai_ml.searches.join("\n"));
  const [files, setFiles] = useState<FileList | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const pick = (p: typeof persona) => { setPersona(p); setFloor(DEFAULTS[p].floor); setMinFixed(DEFAULTS[p].min); setSearches(DEFAULTS[p].searches.join("\n")); };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      unwrap(await api.POST("/api/onboarding", { body: { persona, hourly_floor: floor, min_fixed: minFixed, weekly_connects_budget: budget,
        autonomy: "suggest", marketplace_mode: market,
        saved_searches: searches.split("\n").map((q) => q.trim()).filter(Boolean).map((query) => ({ query, skills: [], limit: 20 })) } }));
      if (files && files.length) {
        const fd = new FormData();
        Array.from(files).forEach((f) => fd.append("files", f));
        await fetch("/api/portfolio/upload", { method: "POST", body: fd, credentials: "include" });
      }
      if (market === "upwork_live") {
        const r = await api.GET("/api/auth/upwork/start");
        const url = (r.data as { authorize_url?: string } | undefined)?.authorize_url;
        if (url) { window.location.href = url; return; }
      }
      nav("/inbox");
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <main style={{ maxWidth: 760, margin: "4vh auto" }}>
      <h1>Set up BidPilot</h1>
      <p className="sub">Choose a portfolio, connect a marketplace, and set your rates, filters and weekly Connects budget.</p>
      {err ? <ErrorBox error={err} /> : null}
      <form className="grid" onSubmit={submit}>
        <fieldset className="card">
          <legend><h2>1. Portfolio</h2></legend>
          <div className="row" role="radiogroup">
            {([["ai_ml", "AI/ML engineer"], ["fullstack", "Full-stack developer"], ["data_analyst", "Data analyst"], ["own", "My own profile"]] as const).map(([k, l]) => (
              <label key={k} className="row" style={{ gap: 6 }}>
                <input type="radio" name="persona" style={{ width: "auto" }} checked={persona === k} onChange={() => pick(k)} data-testid={`persona-${k}`} />{l}
              </label>))}
          </div>
          <label style={{ marginTop: 12 }}>Upload work (Markdown/text case studies, PDF CV) - optional for personas
            <input type="file" multiple accept=".md,.txt,.pdf" onChange={(e) => setFiles(e.target.files)} />
          </label>
        </fieldset>
        <fieldset className="card">
          <legend><h2>2. Marketplace</h2></legend>
          <div className="row">
            <label className="row" style={{ gap: 6 }}><input type="radio" style={{ width: "auto" }} checked={market === "gigsim"} onChange={() => setMarket("gigsim")} />GigSim (simulator)</label>
            <label className="row" style={{ gap: 6 }}><input type="radio" style={{ width: "auto" }} checked={market === "upwork_live"} onChange={() => setMarket("upwork_live")} />Upwork (official MCP, OAuth)</label>
          </div>
          <p className="muted">Live mode only creates drafts; you confirm every proposal on Upwork. No scraping, no browser automation.</p>
        </fieldset>
        <fieldset className="card grid g3">
          <legend><h2>3. Rates & budget</h2></legend>
          <label>Hourly floor ($)<input type="number" min={0} value={floor} onChange={(e) => setFloor(+e.target.value)} data-testid="floor" /></label>
          <label>Minimum fixed price ($)<input type="number" min={0} value={minFixed} onChange={(e) => setMinFixed(+e.target.value)} /></label>
          <label>Weekly Connects budget<input type="number" min={0} value={budget} onChange={(e) => setBudget(+e.target.value)} data-testid="budget" /></label>
        </fieldset>
        <fieldset className="card">
          <legend><h2>4. Saved searches (one per line)</h2></legend>
          <textarea style={{ minHeight: 90 }} value={searches} onChange={(e) => setSearches(e.target.value)} aria-label="Saved searches" />
        </fieldset>
        <button className="primary" disabled={busy} data-testid="finish-onboarding">{busy ? "Saving…" : "Start scouting"}</button>
      </form>
    </main>
  );
}
