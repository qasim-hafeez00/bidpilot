"""SQLite persistence for GigSim (self-contained: no imports from the rest of the repo)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, body TEXT NOT NULL, kind TEXT NOT NULL,
  release_seq INTEGER NOT NULL, released INTEGER NOT NULL DEFAULT 0, released_at REAL);
CREATE TABLE IF NOT EXISTS clients (client_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS freelancers (freelancer_id TEXT PRIMARY KEY, connects INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS proposals (proposal_id TEXT PRIMARY KEY, freelancer_id TEXT NOT NULL, job_id TEXT NOT NULL,
  body TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, submitted_at REAL, decided INTEGER DEFAULT 0,
  UNIQUE(freelancer_id, job_id));
CREATE TABLE IF NOT EXISTS events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, freelancer_id TEXT NOT NULL,
  proposal_id TEXT, thread_id TEXT, type TEXT NOT NULL, body TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages (message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, freelancer_id TEXT NOT NULL,
  sender TEXT NOT NULL, text TEXT NOT NULL, ts REAL NOT NULL, handled INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS idempotency (key TEXT PRIMARY KEY, response TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, freelancer_id TEXT, delta INTEGER, reason TEXT, ts REAL);
"""


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ generic
    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            cur = self.db.execute(sql, args)
            return cur.fetchall()

    def x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            cur = self.db.execute(sql, args)
            return cur.lastrowid or cur.rowcount

    # ------------------------------------------------------------------ seed
    def seeded(self) -> bool:
        return bool(self.q("SELECT 1 FROM jobs LIMIT 1"))

    def seed(self, seed_dir: Path, include_test: bool, test_dir: Path | None, freelancers: list[str], connects: int) -> None:
        with self.lock:
            self.db.execute("BEGIN")
            hist = json.loads((seed_dir / "historical_jobs.json").read_text(encoding="utf-8"))
            for j in hist:
                self.db.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,1,?)", (j["job_id"], json.dumps(j), "historical", -1, 0))
            stream = json.loads((seed_dir / "stream_jobs_dev.json").read_text(encoding="utf-8"))
            if include_test and test_dir and (test_dir / "stream_jobs_test.json").exists():
                stream += json.loads((test_dir / "stream_jobs_test.json").read_text(encoding="utf-8"))
            for i, j in enumerate(stream):
                self.db.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,0,NULL)", (j["job_id"], json.dumps(j), "stream", i))
            clients = json.loads((seed_dir / "clients.json").read_text(encoding="utf-8"))
            if include_test and test_dir and (test_dir / "clients_test.json").exists():
                clients.update(json.loads((test_dir / "clients_test.json").read_text(encoding="utf-8")))
            for cid, c in clients.items():
                self.db.execute("INSERT OR REPLACE INTO clients VALUES (?,?)", (cid, json.dumps(c)))
            for f in freelancers:
                self.db.execute("INSERT OR IGNORE INTO freelancers VALUES (?,?)", (f, connects))
            self.db.execute("COMMIT")

    def release(self, n: int | None = None) -> int:
        now = time.time()
        if n is None:
            return self.x("UPDATE jobs SET released=1, released_at=? WHERE released=0", (now,))
        ids = [r[0] for r in self.q("SELECT job_id FROM jobs WHERE released=0 ORDER BY release_seq LIMIT ?", (n,))]
        for jid in ids:
            self.x("UPDATE jobs SET released=1, released_at=? WHERE job_id=?", (now, jid))
        return len(ids)

    # ------------------------------------------------------------------ helpers
    def job(self, job_id: str) -> dict[str, Any] | None:
        r = self.q("SELECT body, released, kind FROM jobs WHERE job_id=?", (job_id,))
        if not r or not r[0][1]:
            return None
        return json.loads(r[0][0])

    def client(self, client_id: str) -> dict[str, Any] | None:
        r = self.q("SELECT body FROM clients WHERE client_id=?", (client_id,))
        return json.loads(r[0][0]) if r else None

    def idem_get(self, key: str) -> dict | None:
        r = self.q("SELECT response FROM idempotency WHERE key=?", (key,))
        return json.loads(r[0][0]) if r else None

    def idem_put(self, key: str, resp: dict) -> None:
        self.x("INSERT OR IGNORE INTO idempotency VALUES (?,?,?)", (key, json.dumps(resp), time.time()))

    def event(self, fid: str, typ: str, body: dict, proposal_id: str | None = None, thread_id: str | None = None) -> None:
        self.x("INSERT INTO events (freelancer_id, proposal_id, thread_id, type, body, ts) VALUES (?,?,?,?,?,?)",
               (fid, proposal_id, thread_id, typ, json.dumps(body), time.time()))


def default_store() -> Store:
    return Store(os.environ.get("GIGSIM_DB", "data/processed/gigsim.db"))
