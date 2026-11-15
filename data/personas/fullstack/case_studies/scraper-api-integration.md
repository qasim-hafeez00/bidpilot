---
id: fullstack:scraper-api-integration
type: case_study
project: scraper-api-integration
client_industry: travel
date: 2024-11
skills: [REST API, Python, FastAPI]
provenance: synthetic
---

# Partner API integrations hub

## Context
A travel startup integrated 9 supplier APIs by hand. The client was a travel company.

## What I did
Adapter layer with retries, idempotent sync jobs and monitoring. I worked mainly with REST API, Python, FastAPI. Under the hood the system relied on a background worker queue for slow jobs, an in-memory cache and message broker, a relational database.

## Outcome
The project new supplier onboarding from 3 weeks to 4 days.
