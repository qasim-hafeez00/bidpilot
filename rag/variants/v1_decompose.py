"""V1 - requirement decomposition: one dense retrieval per extracted requirement, merged with RRF."""
from rag.pipeline import Flags, retrieve

PRESET = {"scheme": "structured", "query": "decomposed", "hybrid": False, "rerank": False, "multivector": False, "outcome_boost": 0.0}


def retrieve_variant(job, persona, k=10, **kw):
    return retrieve(job, persona, Flags.of(PRESET), k=k, **kw)
