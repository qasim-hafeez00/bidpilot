"""Per-persona index: dense vectors (numpy in-process, or Qdrant when VECTOR_BACKEND=qdrant) + BM25."""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from functools import lru_cache

import bm25s
import numpy as np

from rag.index.models import embed
from rag.ingest import chunkers
from rag.ingest.chunkers import Chunk
from rag.ingest.loaders import Doc, load_persona

TOKEN = re.compile(r"[a-z0-9+#]+")


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


@dataclass
class Index:
    persona: str
    scheme: str
    chunks: list[Chunk]
    vecs: np.ndarray
    bm25: bm25s.BM25
    qdrant_collection: str | None = None

    def dense(self, qvec: np.ndarray, top: int, types: set[str] | None = None) -> list[tuple[int, float]]:
        if self.qdrant_collection:
            return self._qdrant_search(qvec, top, types)
        sims = self.vecs @ qvec
        if types:
            mask = np.array([c.meta.get("type") in types for c in self.chunks])
            sims = np.where(mask, sims, -1e9)
        idx = np.argsort(-sims)[:top]
        return [(int(i), float(sims[i])) for i in idx if sims[i] > -1e8]

    def sparse(self, query: str, top: int, types: set[str] | None = None) -> list[tuple[int, float]]:
        toks = tokenize(query)
        if not toks:
            return []
        scores = self.bm25.get_scores(toks)
        if types:
            scores = np.where(np.array([c.meta.get("type") in types for c in self.chunks]), scores, -1)
        idx = np.argsort(-scores)[:top]
        return [(int(i), float(scores[i])) for i in idx if scores[i] > 0]

    def _qdrant_search(self, qvec: np.ndarray, top: int, types: set[str] | None) -> list[tuple[int, float]]:
        from qdrant_client import models as qm

        flt = qm.Filter(must=[qm.FieldCondition(key="type", match=qm.MatchAny(any=sorted(types)))]) if types else None
        res = _qdrant().query_points(self.qdrant_collection, query=qvec.tolist(), limit=top, query_filter=flt).points
        return [(int(p.id), float(p.score)) for p in res]


@lru_cache(maxsize=1)
def _qdrant():
    from qdrant_client import QdrantClient

    url = os.environ.get("QDRANT_URL")
    return QdrantClient(url=url) if url else QdrantClient(path=os.environ.get("QDRANT_PATH", "data/processed/qdrant"))


def _push_qdrant(name: str, chunks: list[Chunk], vecs: np.ndarray) -> str:
    from qdrant_client import models as qm

    cl = _qdrant()
    if cl.collection_exists(name):
        cl.delete_collection(name)
    cl.create_collection(name, vectors_config=qm.VectorParams(size=vecs.shape[1], distance=qm.Distance.COSINE))
    cl.upsert(name, points=[qm.PointStruct(id=i, vector=v.tolist(), payload={**c.meta, "chunk_id": c.chunk_id})
                            for i, (c, v) in enumerate(zip(chunks, vecs, strict=True))])
    return name


_cache: dict[tuple[str, str], Index] = {}
_lock = threading.Lock()
_extra_docs: dict[str, list[Doc]] = {}


def build(persona: str, scheme: str = "structured", docs: list[Doc] | None = None) -> Index:
    docs = docs if docs is not None else load_persona(persona) + _extra_docs.get(persona, [])
    if scheme == "fixed":
        chunks = chunkers.fixed(docs)
    elif scheme == "contextual":
        chunks = chunkers.contextualize(chunkers.structured(docs))
    else:
        chunks = chunkers.structured(docs)
    vecs = embed([c.text for c in chunks])
    bm = bm25s.BM25()
    bm.index([tokenize(c.text) for c in chunks], show_progress=False)
    coll = None
    if os.environ.get("VECTOR_BACKEND") == "qdrant":
        coll = _push_qdrant(f"bidpilot_{persona}_{scheme}".replace(":", "_"), chunks, vecs)
    return Index(persona, scheme, chunks, vecs, bm, coll)


def get_index(persona: str, scheme: str = "structured") -> Index:
    key = (persona, scheme)
    with _lock:
        if key not in _cache:
            _cache[key] = build(persona, scheme)
        return _cache[key]


def add_documents(persona: str, docs: list[Doc]) -> int:
    """Incremental re-index after a user uploads work (rebuilds only that persona's indexes)."""
    with _lock:
        _extra_docs.setdefault(persona, [])
        known = {d.doc_id for d in _extra_docs[persona]}
        _extra_docs[persona] += [d for d in docs if d.doc_id not in known]
        for key in [k for k in _cache if k[0] == persona]:
            del _cache[key]
    return len(docs)


def invalidate(persona: str | None = None) -> None:
    with _lock:
        for key in [k for k in _cache if persona is None or k[0] == persona]:
            del _cache[key]
