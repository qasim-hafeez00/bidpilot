"""V3 - cross-encoder reranking (MiniLM-L6 ms-marco, ONNX/CPU) of hybrid candidates."""
from rag.pipeline import Flags, retrieve

PRESET = {"scheme": "structured", "query": "whole", "hybrid": True, "rerank": True, "multivector": False, "outcome_boost": 0.0}


def retrieve_variant(job, persona, k=10, **kw):
    return retrieve(job, persona, Flags.of(PRESET), k=k, **kw)
