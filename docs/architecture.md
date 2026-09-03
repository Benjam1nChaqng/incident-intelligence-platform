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
- **Drafting boundary:** creates runbook drafts that remain pending until human approval.
- **Webhook delivery boundary:** records outbound notification attempts with retry state and
  duplicate suppression before any real external integration is connected.
- **CI:** runs pytest and Ruff on pushes and pull requests before public portfolio updates are
  treated as verified.
- **Observability:** emits structured logs and basic counters useful during demos.

## Data Policy

All examples and fixtures must be synthetic or safely redacted. Do not commit real employer,
client, school, personal account, ticket, or log data.

## Current Vertical Slice

The current slice keeps the tested ingestion endpoint, PostgreSQL investigation-history boundary,
deterministic authentication-failure evidence extraction, GitHub Actions CI, a webhook delivery
preview boundary, and a runbook draft preview. Drafts include a deterministic incident
classification, reason codes, operator guidance, and an explicit `pending_human_approval` status.

The live FastAPI app still defaults to the in-memory store so local development and tests do not
require credentials or a running database. A later checkpoint should wire this boundary into
Docker Compose with a local PostgreSQL service and durable webhook and approval state.
