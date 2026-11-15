"""Scout: run saved searches on schedule, de-duplicate (exact id + near-duplicate text), queue new jobs.

Runs in the worker (not in a web request). The per-job bid graph starts at `intake`, which is the Scout's hand-off.
"""
from __future__ import annotations

import re
from typing import Any

from agent.nodes._util import rec, untrusted

SHINGLE = 5


def _norm(t: str) -> str:
    t = re.sub(r"\((reposted|re-?post)\)|- urgent|urgent!?", "", t.lower())
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def shingles(text: str) -> set[str]:
    w = _norm(text).split()
    return {" ".join(w[i: i + SHINGLE]) for i in range(max(1, len(w) - SHINGLE + 1))}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / max(1, len(a | b))


def find_duplicate(job: dict[str, Any], recent: list[dict[str, Any]], threshold: float = 0.8) -> str | None:
    s = shingles(job["title"] + " " + job.get("snippet", job.get("description", ""))[:240])
    for r in recent:
        if r["job_id"] != job["job_id"] and jaccard(s, r["_sh"]) >= threshold:
            return r["job_id"]
    return None


async def scout(toolbox, saved_searches: list[dict[str, Any]], seen_ids: set[str], recent: list[dict[str, Any]],
                posted_after: float = 0.0, trace_id: str | None = None) -> dict[str, Any]:
    """Returns {"new": [job summaries], "duplicates": [(job_id, dup_of)], "trace": [...]}."""
    new, dups, trace = [], [], []
    for s in saved_searches:
        res = await toolbox.call("scout", "search_jobs", {"query": s["query"], "skills": s.get("skills") or None,
                                                          "posted_after": posted_after, "limit": s.get("limit", 20)}, trace_id)
        trace.append(rec("scout", tool="search_jobs", query=s["query"], n=len(res["jobs"])))
        for j in res["jobs"]:
            if j["job_id"] in seen_ids:
                continue
            j["title"] = untrusted(j["title"])
            dup = find_duplicate(j, recent)
            seen_ids.add(j["job_id"])
            entry = {**j, "_sh": shingles(j["title"] + " " + j.get("snippet", "")[:240])}
            recent.append(entry)
            if dup:
                dups.append((j["job_id"], dup))
                continue
            new.append(j)
    return {"new": new, "duplicates": dups, "trace": trace}
