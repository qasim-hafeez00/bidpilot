"""V0 - naive dense baseline: fixed 400-char chunks, top-k cosine on the whole job post."""
from rag.pipeline import Flags, retrieve

PRESET = {"scheme": "fixed", "query": "whole", "hybrid": False, "rerank": False, "multivector": False, "outcome_boost": 0.0}


def retrieve_variant(job, persona, k=10, **kw):
    return retrieve(job, persona, Flags.of(PRESET), k=k, **kw)
