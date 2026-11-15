---
id: fullstack:graphql-gateway
type: case_study
project: graphql-gateway
client_industry: fintech
date: 2023-06
skills: [GraphQL, Node.js, TypeScript]
provenance: synthetic
---

# GraphQL gateway over microservices

## Context
Mobile clients made 14 REST calls per screen. The client was a fintech company.

## What I did
Federated gateway with dataloaders and per-field auth. I worked mainly with GraphQL, Node.js, TypeScript. Under the hood the system relied on a reproducible container image, an in-memory cache and message broker, secure sign-in.

## Outcome
The project screen load calls reduced to 1; payload size down 60%.
