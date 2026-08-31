# Incident Intelligence Flagship Design

**Date:** 2026-08-28
**Status:** Draft for review
**Owner:** Benjamin Chang

## Purpose

Turn the existing Incident Intelligence Platform into Benjamin Chang's primary backend and
applied-AI portfolio project. The system should provide direct, inspectable evidence of software
engineering ability for early-career backend, platform, infrastructure, developer tooling, and
applied-AI roles.

This is not a collection of disconnected interview exercises. It is one coherent service whose
features naturally exercise the coding, database, distributed-systems, testing, reliability, and
AI-evaluation skills commonly assessed in engineering interviews.

## Current State

The repository currently provides:

- A FastAPI application with a health endpoint.
- Strict Pydantic schemas for synthetic support tickets and log events.
- A synthetic authentication-failure fixture.
- `POST /events` with an `Idempotency-Key` header.
- In-memory duplicate suppression.
- Pytest coverage for validation, ingestion, and health behavior.

The current code is a valid starting vertical slice. The design preserves the public behavior of
that slice while replacing process-local state with explicit domain and persistence boundaries.

## Goals

1. Demonstrate production-style backend design through a system Benjamin can explain without
   memorized talking points.
2. Preserve incident evidence and operator decisions in PostgreSQL.
3. Handle duplicate delivery, retries, partial failure, and concurrent workers deliberately.
4. Correlate synthetic ticket and telemetry evidence into an auditable incident timeline.
5. Add deterministic incident classification before introducing an LLM dependency.
6. Evaluate any GPT-backed classifier against a fixed synthetic dataset and report actual quality,
   latency, and cost.
7. Require human approval before an AI-generated draft can become ready for delivery.
8. Provide automated tests, local containers, continuous integration, observability, and a concise
   reproducible demo.
9. Produce truthful portfolio evidence and interview practice from completed behavior only.

## Non-Goals

- Processing real employer, school, customer, or client data.
- Building a general-purpose ticketing product, chat interface, or visual dashboard in the first
  release.
- Automatically sending customer responses or taking remediation actions.
- Training a foundation model or presenting API calls as original machine-learning research.
- Adding Kafka, Kubernetes, Redis, or a vector database before a measured requirement justifies
  them.
- Claiming scale, accuracy, reliability, or cost improvements that were not measured.
- Starting additional portfolio repositories before the flagship demo is reproducible.

## Architecture

### Runtime Components

1. **API process**
   - FastAPI and Pydantic.
   - Validates requests, authenticates operators, applies authorization, and invokes application
     services.
   - Does not contain database queries or provider-specific AI calls in route handlers.

2. **Application services**
   - Coordinate ingestion, incident retrieval, classification, drafting, and approval use cases.
   - Depend on repository and provider protocols rather than concrete infrastructure.
   - Own transaction-level rules such as idempotency conflicts and approval transitions.

3. **PostgreSQL repositories**
   - SQLAlchemy 2 models and repository implementations.
   - Alembic migrations are the authoritative schema history.
   - PostgreSQL 16 is the supported runtime database.
   - In-memory implementations remain available for focused unit tests.

4. **Outbox worker**
   - A separate process in the same Python package.
   - Polls durable jobs from PostgreSQL using bounded batches and row locking.
   - Records attempts, retry eligibility, completion, and terminal failure.
   - Starts with PostgreSQL rather than a separate queue service to keep the first release coherent
     and locally reproducible.

5. **Classifier providers**
   - A deterministic rules classifier is the required baseline.
   - A GPT adapter is optional and disabled by default.
   - Both return the same typed result: category, confidence, cited evidence IDs, explanation, and
     model metadata.

6. **Drafting and approval boundary**
   - Draft generation can use deterministic templates or an optional GPT provider.
   - Drafts begin in `pending_review` and cannot transition directly to a deliverable state.
   - An authenticated operator must explicitly approve or reject a draft.
   - The first release records approval but does not send messages externally.

### Dependency Direction

The package will be organized around inward dependencies:

```text
api/routes -> application/services -> domain models and protocols
                                      ^
infrastructure/postgres --------------|
infrastructure/providers -------------|
worker --------------------------------|
```

Domain and application modules must not import FastAPI, SQLAlchemy, or a model-provider SDK.
Infrastructure implements protocols defined by the application boundary.

## Data Model

The first durable schema will use the following entities:

- `event_ingestions`: unique idempotency key, payload hash, correlation ID, receipt timestamps, and
  the stored response summary.
- `incidents`: correlation ID, status, priority, summary, and lifecycle timestamps.
- `support_tickets`: the normalized synthetic ticket attached to an incident.
- `evidence_events`: immutable normalized log or telemetry evidence with observed time and source.
- `classifications`: provider, category, confidence, cited evidence, explanation, model version,
  prompt version, latency, and optional cost metadata.
- `response_drafts`: generated content, provenance, state, and timestamps.
- `approval_decisions`: operator, decision, reason, and timestamp.
- `outbox_jobs`: job type, payload, state, attempt count, next-attempt time, and last error class.

Identifiers will be generated by the application. Database constraints will enforce unique
correlation IDs, unique idempotency keys, valid state transitions where practical, and referential
integrity. Provider responses and operator decisions remain append-only audit evidence.

## Ingestion Semantics

`POST /events` retains its existing successful response contract and gains durable semantics:

1. Validate the payload before opening a write transaction.
2. Canonicalize the validated payload and compute a stable hash.
3. Insert the idempotency record, incident, ticket, and evidence in one transaction.
4. Return `201 Created` for the first accepted request.
5. Return `200 OK` with the original stored summary when the same key and payload are repeated.
6. Return `409 Conflict` when a key is reused with a different validated payload.
7. Resolve concurrent inserts through the database uniqueness constraint, then reread the winning
   record instead of relying on an application-only check.

No partially persisted incident may be returned as accepted.

## Incident Correlation

The initial fixture supplies a correlation ID, but later synthetic sources may not. Correlation is
implemented as a deterministic application service before any AI assistance:

- Exact correlation ID match wins.
- Otherwise, candidate evidence is limited by a configurable time window and synthetic identity or
  service attributes.
- A scored result records which rules contributed to the match.
- Low-confidence evidence remains unassigned for operator review rather than being forced into an
  incident.

Indexes and query plans will be inspected for correlation and timeline queries. Performance claims
will report the generated dataset size, machine context, test method, and actual measurement.

## Reliable Background Work

Classification and draft-generation requests create outbox jobs in the same transaction as their
request record. The worker follows these rules:

- Claim jobs with row locking so concurrent workers do not process the same attempt.
- Use exponential backoff with a configured maximum delay and attempt count.
- Distinguish retryable provider or network failures from validation and policy failures.
- Store a bounded, redacted error summary without secrets or raw provider credentials.
- Move exhausted jobs to `failed` and expose them for operator inspection.
- Make handlers idempotent so a worker crash after side effects does not create duplicate records.

External webhook delivery is deferred until the internal outbox and failure model are verified.

## API Surface

The planned first-release API is intentionally small:

- `GET /healthz`
- `POST /events`
- `GET /incidents`
- `GET /incidents/{incident_id}`
- `POST /incidents/{incident_id}/classifications`
- `POST /incidents/{incident_id}/drafts`
- `POST /drafts/{draft_id}/approve`
- `POST /drafts/{draft_id}/reject`
- `GET /jobs/{job_id}`

Collection endpoints use cursor pagination with deterministic ordering. Errors use a consistent
problem-details response with a stable application error code, human-readable detail, correlation
ID, and retryability flag.

## Authentication And Authorization

Authentication is introduced after the core persistence and worker boundaries are stable. The
local demo will use signed, short-lived tokens for synthetic operator identities. Roles are:

- `viewer`: read incidents, evidence, classifications, drafts, and job state.
- `operator`: viewer permissions plus request classification, create drafts, approve, and reject.
- `admin`: operator permissions plus retry or cancel failed jobs.

Authorization is enforced in application services as well as routes so alternate interfaces cannot
bypass it. Tokens, API keys, raw prompts containing private data, and provider responses containing
secrets must never be committed.

## Applied AI And Evaluation

AI is an optional provider behind a stable interface, not the architecture's control plane.

The deterministic baseline and GPT-backed classifier will be evaluated on a versioned synthetic
dataset with held-out cases. The report will include:

- Per-category precision, recall, and F1.
- Macro F1 across categories.
- Abstention and unsupported-evidence rates.
- Evidence-citation validity.
- Median and tail latency for the measured run.
- Actual token usage and estimated API cost for the measured run.
- Dataset version, prompt version, model identifier, and run timestamp.

Evaluation code must distinguish measured results from targets. A run can be published when results
are poor if the methodology and failure analysis are honest. GPT calls require an explicit command
and a configured budget; tests and normal development use deterministic fakes.

The separate `bjc-eval` repository remains a later research-style project. Its placeholder claims
must be removed and real results produced before it is promoted in applications. The flagship does
not depend on that repository at runtime.

## Observability

The service will expose enough evidence to debug a demo failure without an external SaaS account:

- Structured JSON logs with request, correlation, incident, and job identifiers.
- Counters for accepted, duplicate, conflicting, rejected, retried, failed, and approved operations.
- Histograms for request and provider latency.
- Health and readiness checks that distinguish process health from database readiness.
- A deterministic failure-injection mode limited to tests and local demos.

Logs must not contain synthetic payload bodies by default. Redaction behavior receives direct tests.

## Testing Strategy

Testing scales with the boundary under test:

1. **Unit tests:** domain rules, hashing, state transitions, retry calculations, correlation scoring,
   and classifier contracts.
2. **API tests:** request validation, response contracts, authorization, pagination, and error
   mapping through `httpx.ASGITransport`.
3. **PostgreSQL integration tests:** migrations, repository behavior, uniqueness races,
   transactions, and worker locking against a disposable database.
4. **Provider contract tests:** deterministic fakes by default; live GPT smoke tests are opt-in and
   budgeted.
5. **Property or generative tests:** idempotency and state-machine invariants where they add useful
   coverage.
6. **Load and failure tests:** measured ingestion, contention, worker restart, and provider-failure
   scenarios with the exact environment reported.
7. **Continuous integration:** formatting or lint, tests, type checking, migration validation, and
   container build.

Every completed checkpoint must leave the repository passing its relevant verification commands.

## Delivery Sequence

The work proceeds as bounded vertical checkpoints:

1. Define the ingestion repository protocol and preserve current API behavior with the in-memory
   implementation.
2. Add PostgreSQL models, configuration, and the first Alembic migration.
3. Implement transactional PostgreSQL ingestion, duplicate rereads, and payload conflicts.
4. Add incident retrieval, timelines, filtering, and cursor pagination.
5. Normalize authentication-failure evidence and add deterministic correlation.
6. Add the durable outbox and single-worker job lifecycle.
7. Prove concurrent worker claims, retries, backoff, and terminal failure.
8. Add deterministic classification and a versioned synthetic evaluation dataset.
9. Add operator authentication and authorization.
10. Add draft creation plus approval and rejection state transitions.
11. Add the optional GPT provider and publish a measured evaluation report.
12. Add structured observability, load and failure testing, CI, containers, demo instructions, and a
    truthful case study.

Each checkpoint is small enough for focused review. Hidden complexity can split a checkpoint, but
later features may not be pulled forward to make a run appear larger.

## Interview And Portfolio Evidence

Every checkpoint summary records:

- The user or system problem being solved.
- The invariant or failure mode that matters.
- The design alternatives considered and the selected tradeoff.
- Relevant time and space complexity where applicable.
- Tests that prove the behavior.
- One interview question Benjamin should be able to answer from the implementation.
- The next highest-value checkpoint.

Only completed, verified behavior appears in the README, resume, LinkedIn, or job applications.
Resume bullets will describe the system and measured outcomes without implying production users or
real client deployment.

## Job-Search Alignment

The private job pipeline should add early-career roles in these families:

- Backend software engineering.
- Platform and infrastructure engineering.
- Developer productivity and internal tooling.
- Cloud or systems software engineering.
- Applied AI engineering and AI evaluation.
- ML platform and data platform engineering.
- Full-stack engineering roles with substantial backend ownership.

The existing compensation floors remain unchanged. Roles that clearly require senior, staff, or
deep research credentials remain excluded from the main queue. Project evidence is considered only
after the corresponding checkpoint is verified.

## Operating Cadence And Cost Controls

- The daily portfolio automation completes at most one bounded checkpoint.
- Normal tests make no paid model calls.
- Live GPT evaluation requires an explicit command, configured key, maximum case count, and recorded
  token or cost output.
- The automation does not push, deploy, purchase services, or expose the repository publicly without
  approval.
- Every seventh completed checkpoint refreshes the README, architecture overview, demo instructions,
  and truthful draft resume evidence.
- The job pipeline remains deterministic first and uses model reasoning only for the strongest
  verified candidates.

## Release Acceptance

The flagship is ready for public portfolio review when all of the following are true:

1. A clean checkout can start the API, worker, and PostgreSQL database from documented commands.
2. Migrations apply successfully to an empty database.
3. Duplicate, conflict, concurrency, retry, and approval invariants have automated coverage.
4. The deterministic classifier has a reproducible evaluation report.
5. Any published GPT comparison contains real results, model metadata, and measured cost.
6. Generated drafts cannot bypass operator approval.
7. CI passes, container images build, and the documented demo has been rerun from a clean state.
8. All fixtures are synthetic and a repository scan finds no credentials or client data.
9. The case study distinguishes implemented behavior, measured results, limitations, and future work.
10. Benjamin can explain the ingestion transaction, idempotency conflict, outbox guarantee,
    correlation method, evaluation design, and approval boundary in a short interview walkthrough.

Deployment is a separate approval-gated decision and is not required to call the repository a
verified local portfolio project.
