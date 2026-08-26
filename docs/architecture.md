# Architecture Overview

## Goal

Incident Intelligence Platform is a portfolio backend that models realistic support operations
without using real customer data. It should be explainable in an interview as a set of small,
tested systems that support incident triage and response drafting.

## Components

- **FastAPI API:** exposes health, ingestion, investigation, webhook, and approval endpoints.
- **Schemas:** validates synthetic tickets, log lines, auth failures, and classifier outputs.
- **Ingestion service:** accepts JSON payloads, enforces idempotency, and records evidence.
- **Investigation store:** persists incident timelines and operator decisions in PostgreSQL.
- **Classifier boundary:** turns evidence into incident categories and confidence explanations.
- **Drafting boundary:** creates runbook or customer-response drafts that require approval.
- **Webhook worker:** delivers outbound notifications with retries and duplicate suppression.
- **Observability:** emits structured logs and basic counters useful during demos.

## Data Policy

All examples and fixtures must be synthetic or safely redacted. Do not commit real employer,
client, school, personal account, ticket, or log data.

## First Vertical Slice

The first slice starts with a tested health endpoint so packaging, local verification, and service
shape are real before adding ingestion behavior.
