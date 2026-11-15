"""V6 - contextual retrieval (deterministic context line from metadata prepended to every chunk)."""
from rag.pipeline import Flags, retrieve

PRESET = {"scheme": "contextual", "query": "whole", "hybrid": True, "rerank": False, "multivector": False, "outcome_boost": 0.0}


def retrieve_variant(job, persona, k=10, **kw):
    return retrieve(job, persona, Flags.of(PRESET), k=k, **kw)
