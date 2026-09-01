# Incident Intelligence Platform

Synthetic support-ticket and log investigation platform for technical support engineering,
AI-adjacent support, and junior software interviews.

## Problem

Support teams often lose time stitching together tickets, authentication failures, logs,
webhooks, retries, and previous investigations. This project demonstrates a small backend
that can ingest synthetic support events, preserve an investigation history, classify incident
patterns, and draft operator-facing responses behind a human approval gate.

No real employer, customer, school, or client data belongs in this repository.

## Smallest Coherent Architecture

- **API service:** Python 3.11+ with FastAPI and Pydantic.
- **Storage target:** PostgreSQL for investigation history, initially abstracted behind tested
  service functions so early checkpoints can run without a database.
- **Incident pipeline:** synthetic ticket/log fixtures, idempotent ingestion, retry-aware webhook
  delivery, and authentication failure normalization.
- **AI boundary:** classifier and runbook draft interfaces with deterministic test doubles first,
  real LLM calls only after secrets and approval gates are in place.
- **Verification:** pytest and ruff locally and in GitHub Actions CI.
- **Runtime:** Docker Compose once the API and PostgreSQL boundary are useful together.

## Roadmap

1. Initialize the service with health checks, project docs, lint, and tests.
2. Add synthetic ticket and log schemas with fixture validation.
3. Add an ingestion endpoint that deduplicates events by idempotency key.
4. Persist investigation history in PostgreSQL through a repository boundary.
5. Normalize authentication failure signals into incident evidence.
6. Add webhook delivery with retry state and duplicate suppression.
7. Add deterministic incident classification and runbook draft interfaces.
8. Add human approval flow before response drafts can be marked ready.
9. Add Docker Compose, basic structured logs, and demo instructions.
10. Refresh the case study and truthful resume bullets every seventh completed checkpoint.

## Development

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```

## Current Checkpoint

Checkpoint 6 adds GitHub Actions CI for the public repository. Every push to `main` and every pull
request now runs the same local verification commands used during development: `python -m pytest`
and `python -m ruff check .`.

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/investigations/auth-failure-preview `
  -ContentType "application/json" `
  -InFile .\tests\fixtures\auth_failure_bundle.json
```
