---
id: fullstack:drf-api
type: case_study
project: drf-api
client_industry: logistics
date: 2024-05
skills: [Django, Django REST Framework, REST API, PostgreSQL]
provenance: synthetic
---

# Logistics REST API

## Context
Drivers' apps hit a slow legacy PHP backend. The client was a logistics company.

## What I did
Rebuilt the API with token auth, pagination and async route optimisation jobs. I worked mainly with Django, Django REST Framework, REST API, PostgreSQL. Under the hood the system relied on a background worker queue for slow jobs, a reproducible container image, secure sign-in.

## Outcome
The project p95 latency from 2.4 s to 310 ms.
