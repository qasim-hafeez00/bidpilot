"""Chunkers. `fixed` = naive fixed-size windows (V0). `structured` = one chunk per natural unit
(case study, README, code file, review, proposal, CV section)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from rag.ingest.loaders import Doc


@dataclass
class Chunk:
    chunk_id: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def project_id(self) -> str | None:
        return self.meta.get("project_id")


def _cid(doc_id: str, i: int, text: str) -> str:
    return f"{doc_id}#{i}-{hashlib.md5(text.encode()).hexdigest()[:6]}"


def fixed(docs: list[Doc], size: int = 400, overlap: int = 60) -> list[Chunk]:
    out = []
    for d in docs:
        t = d.text
        i = 0
        n = 0
        while i < len(t):
            piece = t[i: i + size]
            out.append(Chunk(_cid(d.doc_id, n, piece), piece, dict(d.meta)))
            i += size - overlap
            n += 1
    return out


def structured(docs: list[Doc], max_chars: int = 1800) -> list[Chunk]:
    out = []
    for d in docs:
        if d.meta.get("type") == "cv":
            parts = [p for p in re.split(r"\n(?=[A-Z][A-Za-z ]+\n)|\n## ", d.text) if p.strip()]
        else:
            parts = [d.text[i: i + max_chars] for i in range(0, len(d.text), max_chars)]
        for n, p in enumerate(parts):
            out.append(Chunk(_cid(d.doc_id, n, p), p.strip(), dict(d.meta)))
    return out


def contextualize(chunks: list[Chunk]) -> list[Chunk]:
    """Deterministic context line (V6-lite): prepend persona/type/project/title to each chunk."""
    out = []
    for c in chunks:
        m = c.meta
        ctx = f"[{m.get('type')} | project: {m.get('project_id') or '-'} | {m.get('title')} | industry: {m.get('client_industry') or '-'}]"
        out.append(Chunk(c.chunk_id + ":ctx", f"{ctx}\n{c.text}", dict(m)))
    return out
