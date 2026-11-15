---
id: ai_ml:fraud-anomaly
type: case_study
project: fraud-anomaly
client_industry: fintech
date: 2023-12
skills: [Python, Machine Learning, scikit-learn]
provenance: synthetic
---

# Transaction anomaly detection

## Context
Card fraud was caught only after chargebacks. The client was a fintech company.

## What I did
Isolation forest plus rules with an analyst feedback loop. I worked mainly with Python, Machine Learning, scikit-learn. Under the hood the system relied on a relational database, a reproducible container image.

## Outcome
The project flagged 61% of fraud before settlement at a 0.4% false-positive rate.
