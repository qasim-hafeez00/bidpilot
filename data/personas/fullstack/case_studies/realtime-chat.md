---
id: fullstack:realtime-chat
type: case_study
project: realtime-chat
client_industry: productivity
date: 2023-09
skills: [React, Node.js, WebSockets, MongoDB]
provenance: synthetic
---

# Real-time team chat

## Context
A remote team wanted chat embedded in their project tool. The client was a productivity company.

## What I did
Socket server with presence, typing indicators and message history. I worked mainly with React, Node.js, WebSockets, MongoDB. Under the hood the system relied on an in-memory cache and message broker, a reproducible container image.

## Outcome
The project handled 4,000 concurrent connections in load tests.
