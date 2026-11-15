# RAG variants

Every variant is a preset of the flags in `rag/pipeline.py` (`Flags`), so one command
(`make eval-rag`) reruns the full comparison and `evals/runners/ablation.py` removes one component at a time.

| ID | File | Group | Flags |
|----|------|-------|-------|
| V0 | v0_naive.py | Baseline | fixed chunks, dense, whole post |
| V1 | v1_decompose.py | Query | one retrieval per requirement, RRF merge |
| V2 | v2_hybrid.py | Retrieval | BM25 + dense, RRF |
| V3 | v3_rerank.py | Retrieval | hybrid + cross-encoder rerank |
| V4 | v4_outcome.py | Ranking | hybrid + boost evidence cited by won/replied proposals |
| V5 | v5_multivector.py | Indexing | hybrid + per-type (case study / README / code) max-sum per project |
| V6 | v6_contextual.py | Indexing | metadata context line prepended to every chunk |
| V8 | v8_crag.py | Agentic | LangGraph corrective loop: grade, re-query, refuse when no evidence |
| best | best.py | composite | decomposition + hybrid + rerank + multi-vector + outcome boost |
