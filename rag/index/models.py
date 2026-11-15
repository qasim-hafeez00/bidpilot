"""Open embedding + cross-encoder models (CPU, ONNX via fastembed) with an on-disk embedding cache."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

from common import config as cfg

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_lock = threading.Lock()


@lru_cache(maxsize=1)
def _embedder():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=cfg.get("models.embeddings", "BAAI/bge-small-en-v1.5"),
                         cache_dir=os.environ.get("FASTEMBED_CACHE", str(cfg.ROOT / "data" / "processed" / "models")))


@lru_cache(maxsize=1)
def _reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=cfg.get("models.reranker", "Xenova/ms-marco-MiniLM-L-6-v2"),
                            cache_dir=os.environ.get("FASTEMBED_CACHE", str(cfg.ROOT / "data" / "processed" / "models")))


@lru_cache(maxsize=1)
def _db() -> sqlite3.Connection:
    p = Path(os.environ.get("EMB_CACHE_PATH", cfg.ROOT / "data" / "processed" / "emb_cache.sqlite"))
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(p), check_same_thread=False)
    db.execute("CREATE TABLE IF NOT EXISTS e (k TEXT PRIMARY KEY, v BLOB)")
    return db


def embed(texts: list[str], is_query: bool = False) -> np.ndarray:
    model = cfg.get("models.embeddings", "BAAI/bge-small-en-v1.5")
    texts = [(QUERY_PREFIX + t) if is_query else t for t in texts]
    keys = [hashlib.sha1(f"{model}|{t}".encode()).hexdigest() for t in texts]
    out: list[np.ndarray | None] = [None] * len(texts)
    with _lock:
        db = _db()
        for i, k in enumerate(keys):
            r = db.execute("SELECT v FROM e WHERE k=?", (k,)).fetchone()
            if r:
                out[i] = np.frombuffer(r[0], dtype=np.float32)
        miss = [i for i, v in enumerate(out) if v is None]
        if miss:
            vecs = list(_embedder().embed([texts[i] for i in miss], batch_size=32))
            for i, v in zip(miss, vecs, strict=True):
                v = np.asarray(v, dtype=np.float32)
                v = v / (np.linalg.norm(v) + 1e-9)
                out[i] = v
                db.execute("INSERT OR REPLACE INTO e VALUES (?,?)", (keys[i], v.tobytes()))
            db.commit()
    return np.vstack(out) if out else np.zeros((0, 384), dtype=np.float32)


def rerank(query: str, docs: list[str]) -> np.ndarray:
    """Cross-encoder relevance logits -> sigmoid probabilities in [0, 1]."""
    if not docs:
        return np.zeros(0)
    with _lock:
        logits = np.asarray(list(_reranker().rerank(query, docs, batch_size=32)), dtype=np.float32)
    return 1 / (1 + np.exp(-logits))
