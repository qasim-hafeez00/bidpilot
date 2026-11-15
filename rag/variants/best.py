"""Composite pipeline assembled from the components that won individually (see evals/results/rag_variants.json).
The ablation runner switches each component off in turn."""
from rag.pipeline import Flags, retrieve

PRESET = {"scheme": "structured", "query": "decomposed", "hybrid": True, "rerank": True, "multivector": True, "outcome_boost": 0.3}


def retrieve_variant(job, persona, k=10, **kw):
    return retrieve(job, persona, Flags.of(PRESET), k=k, **kw)
