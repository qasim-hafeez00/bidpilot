"""V2 - hybrid BM25 + dense with reciprocal rank fusion (exact tool names such as Celery, dbt, Pinecone)."""
from rag.pipeline import Flags, retrieve

PRESET = {"scheme": "structured", "query": "whole", "hybrid": True, "rerank": False, "multivector": False, "outcome_boost": 0.0}


def retrieve_variant(job, persona, k=10, **kw):
    return retrieve(job, persona, Flags.of(PRESET), k=k, **kw)
