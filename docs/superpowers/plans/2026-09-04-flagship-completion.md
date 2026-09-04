# Incident Intelligence Flagship Completion Plan

**Goal:** Complete the approved local flagship as one explainable backend system with durable
timeline retrieval, deterministic correlation and classification, reliable jobs, synthetic
operator authorization, approval state, measured evaluation, observability, containers, and an
honest case study.

**Architecture:** Domain models and protocols remain framework-free. FastAPI is the composition
root, SQLAlchemy Core repositories own PostgreSQL operations, Alembic alone changes schema, and a
separate worker claims durable jobs. All default behavior is deterministic and synthetic. Optional
GPT and external delivery remain disabled unless separately approved and configured.

**Constraints:** No real organization data, paid calls, push, deployment, or external messages.
Every behavior begins with a failing test, every schema change has reversible migration coverage,
and every milestone ends with PostgreSQL integration tests plus Ruff.

## Task 1: Incident timeline retrieval

- Create framework-free incident summary/detail/page models and opaque cursor encoding.
- Add a PostgreSQL query repository with deterministic `(created_at, id)` ordering, limit bounds,
  status/priority filters, and ordered evidence timelines.
- Add `GET /incidents` and `GET /incidents/{incident_id}` with stable `404 incident_not_found`.
- Prove no pagination overlap, stable filtering, complete ticket/evidence detail, and safe cursors.
- Commit as `feat: add incident timeline retrieval`.

## Task 2: Deterministic correlation and classification

- Add deterministic candidate scoring using exact correlation, bounded time, synthetic identity,
  and service signals; low confidence abstains with reason codes.
- Add a typed rules classifier returning category, confidence, cited evidence IDs, explanation,
  provider version, prompt version, and measured latency.
- Create a versioned synthetic multi-category evaluation dataset with train/evaluation separation.
- Add a reproducible evaluation command reporting per-class precision/recall/F1, macro F1,
  abstention, citation validity, and latency percentiles as measured values.
- Commit as `feat: add deterministic incident intelligence`.

## Task 3: Durable outbox and worker

- Add Alembic migration `0002_intelligence_jobs` for append-only classifications and durable
  outbox jobs with named state constraints and claim indexes.
- Create classification requests and jobs transactionally.
- Implement bounded PostgreSQL claiming with `FOR UPDATE SKIP LOCKED`, exponential backoff,
  retryable versus terminal failures, bounded redacted errors, and idempotent handlers.
- Expose `POST /incidents/{id}/classifications` and `GET /jobs/{id}`.
- Prove two-worker exclusive claims, retry schedule, exhaustion, and restart-safe completion.
- Commit schema and runtime separately.

## Task 4: Synthetic operator authorization and approvals

- Add Alembic migration `0003_operator_approvals` for response drafts and append-only approval
  decisions.
- Implement signed short-lived HMAC tokens for synthetic viewer/operator/admin identities using a
  required local secret that never appears in source, fixtures, logs, or responses.
- Enforce viewer/operator/admin permissions in application services and API dependencies.
- Persist deterministic drafts in `pending_review`; only operators may approve or reject once.
- Expose draft creation, approval, and rejection endpoints with stable authorization/state errors.
- Prove drafts cannot become approved without an authenticated operator decision.
- Commit schema, auth, and approval slices separately.

## Task 5: Observability and readiness

- Add JSON request logs containing bounded request/correlation identifiers but no payloads.
- Add in-process counters and latency summaries for accepted, duplicate, conflict, rejected,
  retried, failed, and approved operations.
- Add `/readyz` that verifies database reachability separately from `/healthz`.
- Test redaction and readiness failure behavior.
- Commit as `feat: add local operational evidence`.

## Task 6: Containerized runtime, demo, and case study

- Add an API image, worker command, health checks, and Compose services for API, worker, and
  PostgreSQL 16 without embedding secrets.
- Add one deterministic demo script that migrates, ingests, retries, conflicts, retrieves,
  classifies, processes a job, creates a draft, and records an approval using only synthetic data.
- Run migration reversal, full tests, deterministic evaluation, container build/config checks,
  live demo, tracked-content privacy scan, and clean-tree verification.
- Publish a case study with measured results, exact limitations, architecture tradeoffs, interview
  questions, and truthful draft resume bullets. Do not claim deployment or real users.
- Commit as `docs: finish flagship demo and case study`.

## Release gate

The local flagship is complete only when the approved design's ten acceptance checks are mapped to
fresh evidence under `Verified`, `Staged`, or `Incomplete`, with no required item left incomplete.
Deployment and push remain separate approval-gated decisions.
