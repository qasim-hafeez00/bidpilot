---
id: ai_ml:ocr-invoices
type: case_study
project: ocr-invoices
client_industry: accounting
date: 2024-09
skills: [Python, Computer Vision, NLP]
provenance: synthetic
---

# Invoice OCR and field extraction

## Context
An accounting firm keyed in 5,000 invoices a month by hand. The client was a accounting company.

## What I did
Pre-processed scans, ran OCR, extracted totals and vendor fields with a layout model. I worked mainly with Python, Computer Vision, NLP. Under the hood the system relied on classical image pre-processing, a background worker queue for slow jobs, a relational database.

## Outcome
The project 98.1% accuracy on totals; 3 FTE-days saved per week.
