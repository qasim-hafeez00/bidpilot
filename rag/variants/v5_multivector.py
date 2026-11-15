"""V5 - multi-vector items: summary, README and code chunks scored separately, returned as one project."""
from rag.pipeline import Flags, retrieve

PRESET = {"scheme": "structured", "query": "whole", "hybrid": True, "rerank": False, "multivector": True, "outcome_boost": 0.0}


def retrieve_variant(job, persona, k=10, **kw):
    return retrieve(job, persona, Flags.of(PRESET), k=k, **kw)
