"""GigSim - marketplace simulator (REST). Self-contained; BidPilot talks to it only via the Marketplace MCP server.

Realistic frictions: bearer auth per freelancer, per-token rate limit (429 + Retry-After), injected 5xx errors,
idempotency keys on writes, Connects balances, a drip-fed job stream with duplicates / scams / injected text,
policy versions (v2 = the 2 Nov 2026 change request) and simulated clients with hidden preferences.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gigsim import clients_sim
from gigsim.store import Store

SEED = os.environ.get("GIGSIM_SEED", "4016")
ROOT = Path(__file__).resolve().parents[1]
TOKENS = dict(t.split(":") for t in os.environ.get(
    "GIGSIM_TOKENS",
    "dev-token-ai_ml:fl-ai_ml,dev-token-fullstack:fl-fullstack,dev-token-data_analyst:fl-data_analyst,"
    "dev-token-reviewer:fl-reviewer").split(","))
ADMIN_TOKEN = os.environ.get("GIGSIM_ADMIN_TOKEN", "dev-admin")
RPM = int(os.environ.get("GIGSIM_RPM", "120"))
ERROR_RATE = float(os.environ.get("GIGSIM_ERROR_RATE", "0.03"))
DECISION_DELAY = float(os.environ.get("GIGSIM_DECISION_DELAY_S", "20"))

POLICIES: dict[int, dict[str, Any]] = {
    1: {"version": 1, "effective": "2026-10-27", "rules": [
        "No off-platform contact or payment.", "No fabricated experience.", "No guarantees of results.",
        "Fair use of automation: humans approve every submission."],
        "connects": {"base": "job.base_connects", "premium_surcharge": 0}},
    2: {"version": 2, "effective": "2026-11-02", "title": "Platform policy update (change request)", "rules": [
        "No off-platform contact or payment.", "No fabricated experience.", "No guarantees of results.",
        "Fair use of automation: humans approve every submission.",
        "NEW: proposals must not contain external links or URLs (portfolio items are referenced by title).",
        "NEW: premium jobs (Expert level or fixed budget >= $1,000) cost +4 Connects."],
        "connects": {"base": "job.base_connects", "premium_surcharge": 4,
                     "premium_if": "experience_level == 'Expert' or budget >= 1000"},
        "banned_patterns": [r"https?://", r"www\.", r"\b[\w-]+\.(com|io|dev|net|org|me|app)\b"]},
}
STATE = {"policy": int(os.environ.get("GIGSIM_POLICY_VERSION", "1"))}
store: Store


def connects_cost(job: dict) -> int:
    base = int(job.get("connects_cost") or 4)
    pol = POLICIES[STATE["policy"]]
    if pol["connects"]["premium_surcharge"] and (job.get("experience_level") == "Expert" or (job.get("budget") or 0) >= 1000):
        return base + pol["connects"]["premium_surcharge"]
    return base


def public_job(j: dict, released_at: float | None = None) -> dict:
    out = {k: v for k, v in j.items() if k not in ("client",)}
    out["connects_cost"] = connects_cost(j)
    out["posted_at"] = released_at
    out["client_summary"] = {k: j.get("client", {}).get(k) for k in ("payment_verified", "total_spent_usd", "rating",
                                                                       "reviews_count", "hires", "country")}
    return out


# ----------------------------------------------------------------------------- frictions
_hits: dict[str, deque] = defaultdict(deque)
_err_rng = random.Random(int(SEED))


def auth(authorization: str = Header(default="")) -> str:
    tok = authorization.removeprefix("Bearer ").strip()
    if tok == ADMIN_TOKEN:
        return "admin"
    if tok not in TOKENS:
        raise HTTPException(401, "invalid or missing bearer token")
    return TOKENS[tok]


def frictions(request: Request, who: str = Depends(auth)) -> str:
    now = time.time()
    dq = _hits[who]
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= RPM and who != "admin":
        raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(int(60 - (now - dq[0])) + 1)})
    dq.append(now)
    if who != "admin" and ERROR_RATE and _err_rng.random() < ERROR_RATE:
        raise HTTPException(503, "upstream temporarily unavailable (simulated)")
    return who


def _fid(who: str, freelancer_id: str | None) -> str:
    if who == "admin":
        if not freelancer_id:
            raise HTTPException(400, "admin must pass freelancer_id")
        return freelancer_id
    if freelancer_id and freelancer_id != who:
        raise HTTPException(403, "token does not own this freelancer account")
    return who


# ----------------------------------------------------------------------------- lifecycle
async def _background() -> None:
    interval = float(os.environ.get("GIGSIM_STREAM_INTERVAL_S", "60"))
    batch = int(os.environ.get("GIGSIM_STREAM_BATCH", "5"))
    tick = float(os.environ.get("GIGSIM_TICK_S", "10"))
    last_release = 0.0
    while True:
        await asyncio.sleep(tick)
        try:
            if time.time() - last_release > interval:
                store.release(batch)
                last_release = time.time()
            await asyncio.to_thread(run_tick)
        except Exception as e:  # never kill the loop
            print("gigsim background error:", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store
    store = Store(os.environ.get("GIGSIM_DB", str(ROOT / "data" / "processed" / "gigsim.db")))
    if not store.seeded():
        store.seed(Path(os.environ.get("GIGSIM_SEED_DIR", ROOT / "data" / "gigsim_seed")),
                   os.environ.get("GIGSIM_INCLUDE_TEST", "0") == "1", ROOT / "data" / "processed",
                   list(TOKENS.values()), int(os.environ.get("GIGSIM_START_CONNECTS", "400")))
        initial = os.environ.get("GIGSIM_INITIAL_RELEASE", "40")
        store.release(None if initial == "all" else int(initial))
    task = None
    if os.environ.get("GIGSIM_BACKGROUND", "1") == "1":
        task = asyncio.create_task(_background())
    yield
    if task:
        task.cancel()


app = FastAPI(title="GigSim", version="1.2.0", lifespan=lifespan,
              description="Marketplace simulator for BidPilot/GigBid development and grading.")


@app.exception_handler(HTTPException)
async def _http_exc(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail, "status": exc.status_code}, status_code=exc.status_code, headers=exc.headers)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "gigsim", "policy_version": STATE["policy"]}


@app.get("/v1/policy")
def policy(_: str = Depends(frictions)) -> dict:
    return POLICIES[STATE["policy"]]


# ----------------------------------------------------------------------------- read
@app.get("/v1/jobs")
def search_jobs(q: str = "", skills: str = "", posted_after: float = 0.0, hourly: bool | None = None,
                min_budget: float = 0.0, limit: int = Query(20, le=50), offset: int = 0,
                _: str = Depends(frictions)) -> dict:
    terms = [t for t in re.findall(r"[a-z0-9+#.]+", q.lower()) if len(t) > 1]
    want = {s.strip().lower() for s in skills.split(",") if s.strip()}
    rows = store.q("SELECT body, released_at FROM jobs WHERE kind='stream' AND released=1 AND released_at>=? "
                   "ORDER BY released_at DESC, release_seq DESC", (posted_after,))
    hits = []
    for body, rel in rows:
        j = json.loads(body)
        if hourly is not None and j["is_hourly"] != hourly:
            continue
        if min_budget and not j["is_hourly"] and (j.get("budget") or 0) < min_budget:
            continue
        hay = (j["title"] + " " + j["description"] + " " + " ".join(j["skills"])).lower()
        score = sum(t in hay for t in terms) + 2 * len(want & {s.lower() for s in j["skills"]})
        if (terms or want) and score == 0:
            continue
        hits.append((score, rel, j))
    hits.sort(key=lambda h: (-h[0], -h[1]))
    page = hits[offset: offset + limit]
    return {"total": len(hits), "jobs": [{
        "job_id": j["job_id"], "title": j["title"], "snippet": j["description"][:240], "skills": j["skills"],
        "is_hourly": j["is_hourly"], "budget": j.get("budget"), "hourly_low": j.get("hourly_low"),
        "hourly_high": j.get("hourly_high"), "client_id": j["client_id"], "posted_at": rel,
        "connects_cost": connects_cost(j)} for _, rel, j in page]}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str, _: str = Depends(frictions)) -> dict:
    r = store.q("SELECT body, released, released_at FROM jobs WHERE job_id=?", (job_id,))
    if not r or not r[0][1]:
        raise HTTPException(404, "job not found")
    return public_job(json.loads(r[0][0]), r[0][2])


@app.get("/v1/market/stats")
def market_stats(domain: str = "other", kind: Literal["hourly", "fixed"] = "hourly", _: str = Depends(frictions)) -> dict:
    stats = json.loads((Path(os.environ.get("GIGSIM_SEED_DIR", ROOT / "data" / "gigsim_seed")) / "market_stats.json").read_text())
    key = f"{domain}:{kind}"
    if key not in stats:
        raise HTTPException(404, f"no stats for {key}")
    return {"bucket": key, **stats[key], "source": "historical job stream (real Upwork postings, Kaggle)"}


@app.get("/v1/clients/{client_id}/history")
def client_history(client_id: str, _: str = Depends(frictions)) -> dict:
    c = store.client(client_id)
    if not c:
        raise HTTPException(404, "client not found")
    return {k: v for k, v in c.items() if k not in ("hidden_prefs", "is_scammer", "provenance")}


@app.get("/v1/freelancers/{freelancer_id}/connects")
def connects(freelancer_id: str, who: str = Depends(frictions)) -> dict:
    fid = _fid(who, freelancer_id)
    r = store.q("SELECT connects FROM freelancers WHERE freelancer_id=?", (fid,))
    if not r:
        raise HTTPException(404, "freelancer not found")
    return {"freelancer_id": fid, "balance": r[0][0]}


@app.get("/v1/proposals")
def list_proposals(freelancer_id: str | None = None, who: str = Depends(frictions)) -> dict:
    fid = _fid(who, freelancer_id)
    rows = store.q("SELECT proposal_id, job_id, status, body, created_at, submitted_at FROM proposals WHERE freelancer_id=? "
                   "ORDER BY created_at DESC", (fid,))
    return {"proposals": [{"proposal_id": a, "job_id": b, "status": c, "created_at": e, "submitted_at": f,
                           "bid_amount": json.loads(d).get("bid_amount")} for a, b, c, d, e, f in rows]}


@app.get("/v1/events")
def events(freelancer_id: str | None = None, after_id: int = 0, who: str = Depends(frictions)) -> dict:
    fid = _fid(who, freelancer_id)
    rows = store.q("SELECT event_id, proposal_id, thread_id, type, body, ts FROM events WHERE freelancer_id=? AND event_id>? "
                   "ORDER BY event_id LIMIT 200", (fid, after_id))
    return {"events": [{"event_id": a, "proposal_id": b, "thread_id": c, "type": d, "data": json.loads(e), "ts": f}
                       for a, b, c, d, e, f in rows]}


@app.get("/v1/messages")
def list_messages(freelancer_id: str | None = None, thread_id: str | None = None, who: str = Depends(frictions)) -> dict:
    fid = _fid(who, freelancer_id)
    if thread_id:
        rows = store.q("SELECT message_id, thread_id, sender, text, ts FROM messages WHERE freelancer_id=? AND thread_id=? ORDER BY ts",
                       (fid, thread_id))
    else:
        rows = store.q("SELECT message_id, thread_id, sender, text, ts FROM messages WHERE freelancer_id=? ORDER BY ts", (fid,))
    return {"messages": [{"message_id": a, "thread_id": b, "sender": c, "text": d, "ts": e} for a, b, c, d, e in rows]}


# ----------------------------------------------------------------------------- write
class ProposalIn(BaseModel):
    freelancer_id: str | None = None
    job_id: str
    cover_letter: str = Field(min_length=20, max_length=6000)
    screening_answers: list[str] = Field(default_factory=list, max_length=10)
    bid_amount: float = Field(gt=0, le=100000)
    bid_type: Literal["hourly", "fixed"]


class MessageIn(BaseModel):
    freelancer_id: str | None = None
    thread_id: str
    text: str = Field(min_length=1, max_length=4000)


def _idem(key: str | None, who: str, op: str) -> str:
    if not key:
        raise HTTPException(400, "Idempotency-Key header is required for writes")
    return f"{who}:{op}:{key}"


@app.post("/v1/proposals")
def create_draft(p: ProposalIn, idempotency_key: str | None = Header(default=None), who: str = Depends(frictions)) -> dict:
    fid = _fid(who, p.freelancer_id)
    k = _idem(idempotency_key, fid, "draft")
    if (prev := store.idem_get(k)) is not None:
        return {**prev, "idempotent_replay": True}
    job = store.job(p.job_id)
    if not job:
        raise HTTPException(404, "job not found")
    existing = store.q("SELECT proposal_id, status FROM proposals WHERE freelancer_id=? AND job_id=?", (fid, p.job_id))
    if existing:
        pid, status = existing[0]
        if status != "draft":
            raise HTTPException(409, f"proposal already {status} for this job")
        store.x("UPDATE proposals SET body=? WHERE proposal_id=?", (p.model_dump_json(), pid))
    else:
        pid = "pr-" + uuid.uuid4().hex[:10]
        store.x("INSERT INTO proposals VALUES (?,?,?,?,?,?,NULL,0)", (pid, fid, p.job_id, p.model_dump_json(), "draft", time.time()))
    resp = {"proposal_id": pid, "status": "draft", "connects_cost": connects_cost(job)}
    store.idem_put(k, resp)
    return resp


@app.post("/v1/proposals/{proposal_id}/submit")
def submit(proposal_id: str, idempotency_key: str | None = Header(default=None), who: str = Depends(frictions)) -> dict:
    r = store.q("SELECT freelancer_id, job_id, body, status FROM proposals WHERE proposal_id=?", (proposal_id,))
    if not r:
        raise HTTPException(404, "proposal not found")
    fid, job_id, body, status = r[0]
    _fid(who, fid)
    k = _idem(idempotency_key, fid, f"submit:{proposal_id}")
    if (prev := store.idem_get(k)) is not None:
        return {**prev, "idempotent_replay": True}
    if status != "draft":
        raise HTTPException(409, f"proposal already {status}")
    job = store.job(job_id)
    pol = POLICIES[STATE["policy"]]
    letter = json.loads(body)["cover_letter"]
    for pat in pol.get("banned_patterns", []):
        if re.search(pat, letter, re.I):
            raise HTTPException(422, f"policy_violation: v{pol['version']} forbids external links/URLs in proposals")
    cost = connects_cost(job)
    with store.lock:
        bal = store.q("SELECT connects FROM freelancers WHERE freelancer_id=?", (fid,))[0][0]
        if bal < cost:
            raise HTTPException(402, f"insufficient Connects: balance {bal}, cost {cost}")
        store.x("UPDATE freelancers SET connects=connects-? WHERE freelancer_id=?", (cost, fid))
        store.x("INSERT INTO ledger (freelancer_id, delta, reason, ts) VALUES (?,?,?,?)", (fid, -cost, f"submit {proposal_id}", time.time()))
        store.x("UPDATE proposals SET status='submitted', submitted_at=? WHERE proposal_id=?", (time.time(), proposal_id))
    store.event(fid, "submitted", {"job_id": job_id, "connects_spent": cost}, proposal_id=proposal_id)
    resp = {"proposal_id": proposal_id, "status": "submitted", "connects_spent": cost, "balance": bal - cost}
    store.idem_put(k, resp)
    return resp


@app.post("/v1/messages")
def send_message(m: MessageIn, idempotency_key: str | None = Header(default=None), who: str = Depends(frictions)) -> dict:
    fid = _fid(who, m.freelancer_id)
    k = _idem(idempotency_key, fid, "msg")
    if (prev := store.idem_get(k)) is not None:
        return {**prev, "idempotent_replay": True}
    if not store.q("SELECT 1 FROM messages WHERE thread_id=? AND freelancer_id=?", (m.thread_id, fid)):
        raise HTTPException(404, "thread not found")
    mid = "msg-" + uuid.uuid4().hex[:10]
    store.x("INSERT INTO messages VALUES (?,?,?,?,?,?,0)", (mid, m.thread_id, fid, "freelancer", m.text, time.time()))
    resp = {"message_id": mid, "thread_id": m.thread_id, "status": "sent"}
    store.idem_put(k, resp)
    return resp


# ----------------------------------------------------------------------------- simulation tick
def run_tick(force: bool = False) -> dict:
    now = time.time()
    n_dec = n_fu = 0
    rows = store.q("SELECT proposal_id, freelancer_id, job_id, body, submitted_at FROM proposals WHERE status='submitted' AND decided=0")
    for pid, fid, job_id, body, sub in rows:
        if not force and now - (sub or now) < DECISION_DELAY:
            continue
        job = store.job(job_id)
        client = store.client(job["client_id"]) if job else None
        if not job or not client:
            continue
        prop = {**json.loads(body), "proposal_id": pid}
        d = clients_sim.decide(job, client, prop, SEED)
        store.x("UPDATE proposals SET decided=1 WHERE proposal_id=?", (pid,))
        store.event(fid, "viewed", {"job_id": job_id}, proposal_id=pid)
        if d["decision"] == "ignore":
            store.x("UPDATE proposals SET status='not_selected' WHERE proposal_id=?", (pid,))
            store.event(fid, "not_selected", {"job_id": job_id, "decision": d}, proposal_id=pid)
        else:
            intent, text = clients_sim.client_message(job, client, prop, d["decision"], SEED)
            tid = "th-" + pid
            store.x("INSERT INTO messages VALUES (?,?,?,?,?,?,0)", ("msg-" + uuid.uuid4().hex[:10], tid, fid, "client", text, time.time()))
            status = "interview_requested" if d["decision"] == "interview" else "replied"
            store.x("UPDATE proposals SET status=? WHERE proposal_id=?", ("replied", pid))
            store.event(fid, status, {"job_id": job_id, "decision": d, "intent": intent}, proposal_id=pid, thread_id=tid)
        n_dec += 1
    # client reactions to freelancer messages
    for mid, tid, fid, text in store.q("SELECT message_id, thread_id, freelancer_id, text FROM messages WHERE sender='freelancer' AND handled=0"):
        store.x("UPDATE messages SET handled=1 WHERE message_id=?", (mid,))
        pid = tid.removeprefix("th-")
        pr = store.q("SELECT job_id, body FROM proposals WHERE proposal_id=?", (pid,))
        if not pr:
            continue
        job = store.job(pr[0][0])
        client = store.client(job["client_id"])
        ev, reply = clients_sim.followup(client, text, SEED)
        if reply:
            store.x("INSERT INTO messages VALUES (?,?,?,?,?,?,0)", ("msg-" + uuid.uuid4().hex[:10], tid, fid, "client", reply, time.time()))
        if ev == "interview":
            store.x("UPDATE proposals SET status='interview' WHERE proposal_id=?", (pid,))
            store.event(fid, "interview", {"job_id": pr[0][0]}, proposal_id=pid, thread_id=tid)
            prop = {**json.loads(pr[0][1]), "proposal_id": pid}
            hired = clients_sim.hire_after_interview(client, prop, SEED)
            store.x("UPDATE proposals SET status=? WHERE proposal_id=?", ("hired" if hired else "lost", pid))
            store.event(fid, "hired" if hired else "lost", {"job_id": pr[0][0]}, proposal_id=pid, thread_id=tid)
        elif ev == "replied":
            store.event(fid, "message", {"text_preview": (reply or "")[:80]}, proposal_id=pid, thread_id=tid)
        n_fu += 1
    return {"decided": n_dec, "followups": n_fu}


def _admin(who: str = Depends(auth)) -> None:
    if who != "admin":
        raise HTTPException(403, "admin only")


@app.post("/v1/admin/tick", dependencies=[Depends(_admin)])
def admin_tick(force: bool = True) -> dict:
    return run_tick(force=force)


@app.post("/v1/admin/release", dependencies=[Depends(_admin)])
def admin_release(n: int | None = None) -> dict:
    return {"released": store.release(n)}


@app.post("/v1/admin/policy", dependencies=[Depends(_admin)])
def admin_policy(version: int) -> dict:
    if version not in POLICIES:
        raise HTTPException(400, "unknown policy version")
    STATE["policy"] = version
    return POLICIES[version]


@app.post("/v1/admin/connects", dependencies=[Depends(_admin)])
def admin_connects(freelancer_id: str, balance: int) -> dict:
    store.x("INSERT OR REPLACE INTO freelancers VALUES (?,?)", (freelancer_id, balance))
    return {"freelancer_id": freelancer_id, "balance": balance}


@app.get("/v1/admin/stats", dependencies=[Depends(_admin)])
def admin_stats() -> dict:
    rows = store.q("SELECT freelancer_id, status, COUNT(*) FROM proposals GROUP BY 1, 2")
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for f, s, n in rows:
        out[f][s] = n
    return {"by_freelancer": out, "policy": STATE["policy"]}
