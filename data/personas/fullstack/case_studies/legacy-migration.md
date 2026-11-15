---
id: fullstack:legacy-migration
type: case_study
project: legacy-migration
client_industry: nonprofit
date: 2023-04
skills: [Django, PHP, PostgreSQL]
provenance: synthetic
---

# PHP to Django migration

## Context
A donor database ran on unmaintained PHP code. The client was a nonprofit company.

## What I did
Incremental strangler migration with data validation scripts. I worked mainly with Django, PHP, PostgreSQL. Under the hood the system relied on a reproducible container image, a background worker queue for slow jobs.

## Outcome
The project migrated 210k donor records with zero data loss.
