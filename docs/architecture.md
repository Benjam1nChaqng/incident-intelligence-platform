# Architecture Overview

## System boundary

The platform models a realistic support investigation without real customer data. FastAPI is the
composition root, framework-free domain models define contracts, SQLAlchemy Core repositories own
PostgreSQL operations, Alembic alone changes schema, and a separate worker performs classification.
The default intelligence path is deterministic and makes no network or paid-model call.

The first release is a trusted loopback demo. Compose publishes API and database ports only on
`127.0.0.1`. Ingestion and preview routes are unauthenticated; investigation retrieval, job
operations, and draft decisions use signed roles. Moving this boundary onto a network requires
ingestion authentication, rate limiting, TLS, and a production identity integration.

```text
synthetic event bundle
        |
        v
  FastAPI validation -----> stable problem response
        |
        v
 PostgreSQL transaction: receipt + incident + ticket + evidence
        |
        +------> cursor-paginated incident timeline
        |
        +------> durable classification job
        |                |
        |                v
        |     SKIP LOCKED worker claim
        |                |
        |                v
        |     append-only classification
        |
        +------> pending response draft from stored evidence
                         |
                         v
              signed operator decision
```

## Ingestion transaction

The validated event bundle is serialized with sorted object keys and hashed with SHA-256. A single
transaction inserts the idempotency receipt, incident, normalized ticket, and every evidence event.
`ON CONFLICT DO NOTHING RETURNING` establishes one database winner. A matching committed hash
returns the stored response as a duplicate; a changed hash is a conflict. PostgreSQL uniqueness
also owns correlation, ticket, and evidence identity. Any child failure rolls the entire receipt
and incident back.

## Timeline and intelligence

Incident pages use deterministic `(created_at, id)` descending order and opaque cursor positions.
Evidence is returned by observation time, which lets classifier results cite exact event IDs.
The deterministic correlation helper uses exact correlation ID first, then bounded identity,
service, and time signals; weak scores abstain. It does not automatically merge stored incidents.
The rules classifier returns category, confidence, reason codes, cited evidence,
provider/model/prompt versions, and measured latency. Saved results can be retrieved by their
classification ID after the job completes.
Draft creation is a separate explicit operator request using stored incident evidence; it does not
require a completed classification or automatically enqueue a second generation job.

## Durable jobs

Classification requests become `outbox_jobs`. Workers claim bounded due batches with row locks and
`SKIP LOCKED`, increment attempts atomically, and receive a unique claim token for each attempt.
The worker name identifies a process; the token identifies its current authority to change a job.
Completion and failure transitions check that token so an old worker cannot overwrite a later
claim, even when a restarted worker has the same name.

Claims have a bounded lease. Later polls reclaim expired processing jobs while attempts remain;
expired jobs at the attempt limit become terminal failures with `WorkerLeaseExpired`. Retryable
failures use exponential backoff capped at five minutes, and exhausted or non-retryable jobs remain
inspectable. Completion locks the job, inserts one classification, and marks the job complete in
one transaction. Replaying an already completed job returns the original result ID. An authenticated
admin can explicitly requeue a failed job; ordinary operators cannot reset its retry budget.

## Authorization and approval

Local synthetic identities use short-lived HMAC-SHA256 tokens. The secret comes from environment
configuration and is never stored in fixtures, responses, or logs. Viewer, operator, and admin
permissions are checked before protected API actions and again in framework-independent
application services. Repository adapters are trusted internal storage components, not public
authorization interfaces. Admin-only retry is separate from operator
classification and draft actions. Drafts begin in `pending_review`; an
operator or admin can append exactly one approval decision and atomically move the draft to
`approved` or `rejected`. A unique decision constraint and row lock protect alternate callers and
concurrent requests.

## Operational evidence

`/healthz` proves the process is alive. `/readyz` separately executes a database query. The packaged
API configures its application logger to emit JSON; request bodies and bearer tokens are excluded.
Operational fields include request identity, method, route, status, and latency. Caller-provided
metadata must pass the logging boundary before it can appear in these records.

API `/metrics` reports counters and request latency for that API process only. A separate worker
keeps its own retry/failure counters and emits structured operational records; these counters are
not aggregated into API `/metrics`. Restarting either process resets its local metrics. Durable
job state and result history remain in PostgreSQL. External metrics storage, dashboards, and
alerting are deferred.

## Durable schema

- `event_ingestions`, `incidents`, `support_tickets`, and `evidence_events` own ingestion history.
- `classifications` stores immutable classifier results with evidence citations and provenance.
- `outbox_jobs` owns attempts, claims, retry scheduling, terminal state, and result linkage.
- `response_drafts` owns generated content and review state.
- `approval_decisions` is the append-only record of the authenticated human decision.

Migrations `0001_foundation`, `0002_intelligence_jobs`, `0003_operator_approvals`, and
`0004_job_claim_ownership` are reversible and use named keys, constraints, and indexes. Migration
0004 adds the per-attempt claim token and a foreign key from the completed job to its classification.

## Deliberate tradeoffs

- SQLAlchemy Core keeps transactions explicit; an ORM could reduce mapping code but hide fewer
  concurrency details in an interview project.
- PostgreSQL is mandatory for durable behavior because lock and conflict semantics are part of the
  design. Memory mode exists only for bounded unit and preview tests.
- HMAC tokens are intentionally small and local. A production system would delegate identity,
  rotation, revocation, and audit integration to an identity provider.
- Rules provide a reproducible baseline. Optional GPT work remains outside the control plane and is
  deferred until there is a larger held-out dataset and an explicit budget.
- Process-local metrics make the demo inspectable without SaaS. Production would export standard
  metrics and traces to durable monitoring.
