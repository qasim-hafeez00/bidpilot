"""Retriever factory: the deployed variant is chosen in agent/config.yaml (rag.variant), by measurement (R6)."""
from __future__ import annotations

import importlib
from typing import Any

from common import config as cfg
from rag.pipeline import ProjectHit

VARIANTS = {
    "v0": "rag.variants.v0_naive", "v1": "rag.variants.v1_decompose", "v2": "rag.variants.v2_hybrid",
    "v3": "rag.variants.v3_rerank", "v4": "rag.variants.v4_outcome", "v5": "rag.variants.v5_multivector",
    "v6": "rag.variants.v6_contextual", "v8": "rag.variants.v8_crag", "best": "rag.variants.best",
}


def get(name: str | None = None):
    return importlib.import_module(VARIANTS[name or cfg.get("rag.variant", "best")])


def retrieve(job: dict[str, Any], persona: str, k: int | None = None, variant: str | None = None, **kw: Any) -> list[ProjectHit]:
    return get(variant).retrieve_variant(job, persona, k=k or cfg.get("rag.k", 8), **kw)
