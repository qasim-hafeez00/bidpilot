"""Isolated evaluation environment: a fresh GigSim process (own DB, own accounts, no injected errors, tick on demand)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import contextmanager

import httpx

from evals.runners.common import ROOT

ADMIN = {"Authorization": "Bearer dev-admin"}


@contextmanager
def eval_gigsim(accounts: list[str], port: int = 18091, include_test: bool = False):
    """accounts: freelancer ids; token for account X is 'tok-X'. Yields base URL."""
    db = ROOT / "data" / "processed" / f"gigsim_eval_{port}.db"
    for suffix in ("", "-wal", "-shm"):
        p = db.with_name(db.name + suffix)
        if p.exists():
            p.unlink()
    env = {**os.environ, "GIGSIM_DB": str(db), "GIGSIM_ERROR_RATE": "0", "GIGSIM_BACKGROUND": "0", "GIGSIM_INITIAL_RELEASE": "all",
           "GIGSIM_DECISION_DELAY_S": "0", "GIGSIM_RPM": "100000", "GIGSIM_INCLUDE_TEST": "1" if include_test else "0",
           "GIGSIM_TOKENS": ",".join(f"tok-{a}:{a}" for a in accounts), "GIGSIM_START_CONNECTS": "5000"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "gigsim.app:app", "--port", str(port), "--log-level", "warning"],
                            cwd=ROOT, env=env)
    base = f"http://localhost:{port}"
    try:
        for _ in range(120):
            try:
                if httpx.get(base + "/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(1)
        old = os.environ.get("GIGSIM_BASE_URL")
        os.environ["GIGSIM_BASE_URL"] = base
        yield base
    finally:
        if old is not None:
            os.environ["GIGSIM_BASE_URL"] = old
        proc.terminate()
        proc.wait(timeout=20)


def tick(base: str) -> dict:
    return httpx.post(base + "/v1/admin/tick", headers=ADMIN, timeout=600).json()


def outcomes(base: str, freelancer: str) -> dict[str, str]:
    """proposal_id -> furthest status."""
    r = httpx.get(base + "/v1/proposals", params={"freelancer_id": freelancer}, headers=ADMIN, timeout=30).json()
    return {p["proposal_id"]: p["status"] for p in r["proposals"]}
