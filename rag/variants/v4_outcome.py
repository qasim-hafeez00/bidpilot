"""V4 - outcome-aware ranking: boost evidence cited by past proposals that won or got replies."""
from rag.pipeline import Flags, retrieve

PRESET = {"scheme": "structured", "query": "whole", "hybrid": True, "rerank": False, "multivector": False, "outcome_boost": 0.5}


def retrieve_variant(job, persona, k=10, **kw):
    return retrieve(job, persona, Flags.of(PRESET), k=k, **kw)
