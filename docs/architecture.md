# Architecture Overview

## Goal

Incident Intelligence Platform models a realistic support investigation without using real
customer data. The current vertical slice focuses on a hard backend problem that is useful in
interviews: accepting retries safely while committing a multi-table incident atomically under
concurrent load.

## Request flow

1. FastAPI validates the incoming `EventBundle` before storage code runs.
2. The ingestion adapter serializes the validated model with sorted JSON object keys and hashes it.
3. PostgreSQL attempts to insert an idempotency receipt using `ON CONFLICT DO NOTHING RETURNING`.
4. A receipt collision rereads the committed payload hash and response summary. Equal content is a
   duplicate; changed content is an idempotency conflict.
5. A new receipt is followed by one incident, one normalized support ticket, and every evidence
   event inside the same database transaction.
6. PostgreSQL uniqueness decides correlation conflicts and concurrent winners. Any failed child
   insert rolls the receipt and all related rows back.

The API is built by `create_app`. A caller must inject a store or explicitly select `memory` or
`postgres` through validated settings. PostgreSQL configuration never degrades silently to an
in-memory process.

## Durable schema

- `event_ingestions` owns the idempotency key, canonical payload hash, correlation ID, and stored
  success response.
- `incidents` owns the generated UUID, unique correlation ID, open status, priority, and summary.
- `support_tickets` normalizes the source ticket and belongs to exactly one incident.
- `evidence_events` stores timestamped synthetic log evidence and belongs to exactly one incident.

Alembic migration `0001_foundation` is the only durable schema authority. Foreign keys prevent
orphaned child records. Named indexes cover correlation lookup, ticket-to-incident lookup, and
incident evidence ordered by observation time.

## Public ingestion contract

| Condition | HTTP status | Application code or state | Retryable |
| --- | ---: | --- | --- |
| New key and correlation | 201 | `accepted` | Not applicable |
| Same key and canonical payload | 200 | `duplicate` | Not applicable |
| Same key, changed payload | 409 | `idempotency_key_reused` | No |
| Different key, same correlation | 409 | `correlation_id_reused` | No |
| Database unavailable | 503 | `storage_unavailable` | Yes |

Database engines hide bound statement parameters. Public storage errors do not include request
payloads, credentials, or connection strings.

## Adjacent preview boundaries

- Authentication-failure evidence extraction is deterministic and returns reasoned synthetic
  signals.
- Runbook drafting returns `pending_human_approval`; it cannot approve or send its own output.
- Webhook delivery is an in-memory preview that demonstrates retry state and duplicate suppression;
  no real destination is connected.

These boundaries remain deliberately separate from durable ingestion until their own lifecycle,
authorization, retry, and audit semantics are designed and migrated.

## Verification boundary

The test suite exercises migration upgrade/downgrade, all four persisted tables, exact duplicate
rereads, both conflict types, full rollback, two-thread concurrency, application wiring, and safe
database-unavailable behavior against PostgreSQL 16. GitHub Actions starts PostgreSQL 16, applies
Alembic, runs the entire suite, and then runs Ruff.

## Not yet implemented

Background workers, authentication and authorization, persisted classifier outputs, approval
decisions, outbound integrations, optional GPT evaluation, production deployment, and operational
dashboards remain future milestones. No current preview endpoint writes to an external system.
