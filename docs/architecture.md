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

## Current Vertical Slice

The current slice keeps the tested ingestion endpoint and PostgreSQL investigation-history
boundary, then adds deterministic authentication-failure evidence extraction. Given a synthetic
event bundle, the API can return normalized signals such as MFA denial, account lockout, and
repeated failures, plus affected synthetic users and a support-facing summary.

The live FastAPI app still defaults to the in-memory store so local development and tests do not
require credentials or a running database. A later checkpoint should wire this boundary into
Docker Compose with a local PostgreSQL service.
