---
id: fullstack:saas-dashboard
type: case_study
project: saas-dashboard
client_industry: SaaS
date: 2025-04
skills: [React, TypeScript, Django, PostgreSQL]
provenance: synthetic
---

# Multi-tenant SaaS analytics dashboard

## Context
A startup's customers wanted self-serve usage analytics. The client was a SaaS company.

## What I did
Tenant-scoped API, background aggregation jobs and a charting UI. I worked mainly with React, TypeScript, Django, PostgreSQL. Under the hood the system relied on a background worker queue for slow jobs, an in-memory cache and message broker, a reproducible container image.

## Outcome
The project dashboard load time under 1.2 s for 50k-row tenants.
