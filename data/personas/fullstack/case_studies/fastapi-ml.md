---
id: fullstack:fastapi-ml
type: case_study
project: fastapi-ml
client_industry: agritech
date: 2025-02
skills: [FastAPI, Python, Docker]
provenance: synthetic
---

# Serving an ML model behind FastAPI

## Context
A data science team could not expose their model to the mobile app. The client was a agritech company.

## What I did
Typed API with request validation, caching and autoscaling container. I worked mainly with FastAPI, Python, Docker. Under the hood the system relied on an in-memory cache and message broker, cloud infrastructure.

## Outcome
The project serves 30 requests/s at p95 180 ms.
