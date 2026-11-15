---
id: ai_ml:legal-rag
type: case_study
project: legal-rag
client_industry: legal services
date: 2025-03
skills: [Python, RAG, LLM, LangChain]
provenance: synthetic
---

# Contract Q&A assistant over 12k legal documents

## Context
Paralegals spent hours searching contracts for clauses. The client was a legal services company.

## What I did
Chunked contracts by clause, added hybrid retrieval and citation-checked answers. I worked mainly with Python, RAG, LLM, LangChain. Under the hood the system relied on a managed similarity-search index, a typed async Python web service, a reproducible container image.

## Outcome
The project cut clause lookup time from 25 minutes to under 2 minutes; 91% answer accuracy on a 200-question test set.
