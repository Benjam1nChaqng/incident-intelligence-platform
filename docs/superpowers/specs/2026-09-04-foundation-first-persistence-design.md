# Foundation-First Persistence Design

**Date:** 2026-09-04  
**Status:** Draft for user review  
**Owner:** Benjamin Chang

## Relationship To The Flagship Design

This document refines the persistence foundation in the existing Incident Intelligence Flagship
Design. It does not replace the overall product design. It resolves the gap between that design and
the current repository, where PostgreSQL exists only as an unconnected repository sketch and the
running FastAPI application still stores ingestion state in process memory.

The foundation must become real before adding approval persistence. Otherwise the project would
accumulate another convincing-looking in-memory workflow without satisfying the flagship's durable
data, failure-handling, and reproducibility requirements.

## Decision Summary

Build the database foundation as the next architectural milestone:

1. Add a PostgreSQL 16 service for local development through Docker Compose.
2. Make Alembic migrations the only authoritative way to create or change the durable schema.
3. Add SQLAlchemy 2 and psycopg infrastructure behind the existing ingestion boundary.
4. Persist the ingestion receipt, incident, ticket, and evidence events in one transaction.
5. Preserve the existing `POST /events` success response while adding payload-conflict detection.
6. Prove migrations, duplicate rereads, conflicts, rollback, and concurrent ingestion against a
   disposable PostgreSQL database.
7. Keep the in-memory implementation only as an explicitly selected test and lightweight demo
   adapter.

No cloud deployment, paid service, real client data, or external message delivery is included.

## Approaches Considered

### 1. Foundation first, selected

Wire a real PostgreSQL runtime and prove transaction semantics before building later workflows.
This requires more initial work than an in-memory endpoint, but every subsequent incident,
background job, authentication, and approval feature can then use the same durable boundary.

### 2. Approval endpoints first, rejected

Adding approve and reject endpoints over another process-local dictionary would create visible API
surface quickly. It would not preserve decisions across restarts and would have to be rewritten
once PostgreSQL is connected. That is activity without meaningful movement toward release
acceptance.

### 3. Complete the entire flagship in one change, rejected

Combining persistence, retrieval, workers, authentication, approvals, GPT evaluation,
observability, and demo packaging would make failures difficult to isolate and review. The full
goal remains intact, but implementation will proceed through coherent, verifiable milestones.

## Goals

- A clean checkout can start a disposable PostgreSQL 16 database using a documented command.
- A migration can create the durable ingestion schema in an empty database and downgrade it during
  development verification.
- `POST /events` writes one complete incident transaction or no incident data at all.
- Repeating the same idempotency key with the same canonical payload returns the original stored
  response with `200 OK`.
- Reusing an idempotency key with different canonical content returns `409 Conflict` and performs
  no writes.
- Concurrent requests for the same idempotency key resolve through a database constraint and both
  return the same stored result.
- Existing health, schema, classification, runbook-preview, and webhook-preview behavior remains
  covered by tests.

## Non-Goals

- Incident listing, timeline queries, filtering, or cursor pagination.
- Durable outbox jobs or a background worker.
- Operator authentication, authorization, or approval state.
- A live GPT provider or paid evaluation run.
- A production deployment or managed database.
- Kafka, Redis, Kubernetes, a vector database, or caching.
- API or worker containers beyond what is needed to reproduce the local PostgreSQL foundation.

## Runtime Architecture

The milestone has three boundaries:

```text
FastAPI route
    -> ingestion service and IngestionStore protocol
        -> InMemoryIngestionStore (explicit unit-test adapter)
        -> PostgresIngestionStore (durable runtime adapter)
            -> PostgreSQL 16 schema managed by Alembic
```

The route will receive an ingestion service through application construction rather than importing
a process-global concrete store. `create_app(...)` will allow tests to inject the in-memory adapter.
The Docker Compose runtime will explicitly select PostgreSQL and provide its database URL through
environment variables.

Direct `uvicorn` development without database configuration may explicitly select the memory
adapter. Documentation must label that mode non-durable. The reproducible flagship demo will use
PostgreSQL.

## Configuration

Configuration will use environment variables with no committed secrets:

- `INCIDENT_INTEL_STORAGE_BACKEND`: `memory` or `postgres`.
- `INCIDENT_INTEL_DATABASE_URL`: required when the backend is `postgres`.

`.env.example` will contain names and safe placeholders only. Docker Compose may use clearly
documented local-only development values supplied through an ignored `.env` file. Missing or
invalid PostgreSQL configuration must fail at application startup with a concise error rather than
silently falling back to memory.

## Durable Data Model

The first Alembic migration will create:

### `event_ingestions`

- `idempotency_key`, primary key
- `payload_hash`, required SHA-256 digest of canonical validated JSON
- `correlation_id`, required
- `response_summary`, required JSONB containing the successful response contract
- `created_at`, required timezone-aware timestamp

### `incidents`

- generated UUID primary key
- `correlation_id`, unique and required
- `status`, initially `open`
- `priority`, copied from the synthetic support ticket
- `summary`, copied from the ticket subject
- `created_at` and `updated_at`

### `support_tickets`

- `ticket_id`, primary key
- `incident_id`, required foreign key
- normalized subject, description, priority, source, requester role, creation time, and tags

### `evidence_events`

- `event_id`, primary key
- `incident_id`, required foreign key
- observed time, service, severity, message, synthetic user ID, and JSONB attributes

Foreign keys will prevent orphaned tickets and evidence. Indexes will cover incident correlation ID,
ticket incident ID, and evidence incident/time ordering. Later migrations will add classifications,
jobs, drafts, and approval decisions without rewriting this migration.

For this milestone, reusing a correlation ID under a different idempotency key is rejected with a
stable `correlation_id_reused` conflict. This avoids silently merging two independently submitted
bundles before incident-update semantics are designed.

## Canonicalization And Idempotency

The validated `EventBundle` will be serialized with deterministic key ordering and normalized JSON
representations before hashing. The hash is computed from validated application data, not raw
request bytes, so insignificant JSON key order does not create a false conflict.

The ingestion transaction will:

1. Attempt to insert the idempotency receipt.
2. If the key already exists, reread the stored payload hash and response summary.
3. Return the stored response when hashes match.
4. Raise an idempotency conflict when hashes differ.
5. For a new key, insert the incident, support ticket, and every evidence event.
6. Store the response summary and commit only after all related rows are valid.

Database uniqueness constraints, not an application-only pre-check, decide concurrent winners.
The losing transaction rereads the committed receipt. No partial incident can be returned as
accepted.

## API And Error Contract

The existing successful response remains unchanged:

- `201 Created` for the first accepted bundle.
- `200 OK` with `status: duplicate` for the same key and canonical bundle.

Conflicts return `409` using a problem-details body with:

- stable application code: `idempotency_key_reused` or `correlation_id_reused`
- human-readable detail
- correlation ID when known
- `retryable: false`

Database unavailability returns a stable `503 storage_unavailable` response with
`retryable: true`. Error responses and logs must not include payload bodies, credentials, or
connection strings.

## Testing Strategy

Development follows test-driven development. Each production behavior is introduced only after a
test fails for the expected missing behavior.

### Unit and API tests

- Canonical hashing is stable across equivalent validated payloads.
- The in-memory adapter matches the durable adapter's duplicate and conflict contract.
- App construction injects the selected store without global state leaking across tests.
- API responses preserve the existing success schema and map domain errors to stable HTTP errors.

### PostgreSQL integration tests

- Upgrade an empty database to Alembic head.
- Insert a complete first bundle and inspect all four tables.
- Repeat the same key and payload and reread the original summary.
- Reuse the key with changed content and verify `409` with no extra rows.
- Reuse a correlation ID under a different key and verify no partial writes.
- Force a ticket or evidence failure and verify the entire transaction rolls back.
- Run two concurrent ingestions with the same key and verify one stored transaction and consistent
  responses.
- Downgrade and re-upgrade the migration during local verification.

### Continuous integration

CI will retain the fast unit and lint checks and add a PostgreSQL service job that:

1. Installs the package and database dependencies.
2. Applies migrations to an empty database.
3. Runs the marked integration suite.
4. Runs the full test suite and Ruff.

Container-image verification for the API and worker remains part of the final delivery milestone.

## Planned File Boundaries

- `src/incident_intel/ingestion.py`: records, domain errors, canonical hashing, protocol, and
  in-memory adapter.
- `src/incident_intel/postgres.py`: SQLAlchemy tables and the PostgreSQL ingestion adapter.
- `src/incident_intel/config.py`: validated storage settings.
- `src/incident_intel/api.py`: application factory, dependency wiring, and error mapping.
- `migrations/`: Alembic environment and the immutable initial schema revision.
- `tests/`: unit, API, migration, transaction, rollback, and concurrency coverage.
- `compose.yaml`: disposable PostgreSQL 16 service for local development and tests.
- `.env.example`: non-secret configuration contract.
- `.github/workflows/ci.yml`: PostgreSQL integration verification.
- `README.md` and `docs/architecture.md`: truthful startup, durability, and limitation notes.

The current `PostgresInvestigationHistoryStore.schema_sql()` helper and its fake-cursor schema test
will be removed after the Alembic migration and real PostgreSQL integration tests replace them.
Application startup and tests must never call `metadata.create_all()` as a second schema authority.

## Verification Contract

The milestone is complete only when fresh output proves all of the following:

1. Unit and API tests pass.
2. PostgreSQL integration tests pass against a newly created disposable database.
3. Alembic upgrades an empty database, downgrades it, and upgrades it again.
4. Ruff reports no violations.
5. `git diff --check` reports no whitespace errors.
6. A repository scan finds no credentials, connection strings, or non-synthetic identifiers.
7. Documentation reproduces the PostgreSQL-backed ingestion flow from a clean checkout.

Passing mock-based tests alone is not sufficient evidence for this milestone.

## Next Milestone

After this foundation is verified, implement incident retrieval and an auditable timeline with
filtering and cursor pagination. Durable jobs, authentication, approvals, measured AI evaluation,
observability, and the polished demo remain required by the active flagship goal.
