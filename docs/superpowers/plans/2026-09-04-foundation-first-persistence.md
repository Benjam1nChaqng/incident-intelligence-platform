# Foundation-First Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mock-only PostgreSQL boundary with a migrated, transactional PostgreSQL ingestion path that preserves the existing API contract and proves duplicate, conflict, rollback, and concurrency behavior.

**Architecture:** Keep ingestion rules and protocols in `ingestion.py`, construct FastAPI with an injected store, and place SQLAlchemy/PostgreSQL details in `postgres.py`. Alembic owns the schema, Docker Compose supplies a disposable PostgreSQL 16 service, and the in-memory adapter remains an explicitly selected unit-test adapter.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLAlchemy 2, psycopg 3, Alembic, PostgreSQL 16, pytest, httpx, Ruff, Docker Compose, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-09-04-foundation-first-persistence-design.md`

## Global Constraints

- All fixtures and examples are synthetic; no employer, client, school, account, or credential data may be committed.
- `POST /events` remains `201` for a new bundle and `200` for the same key and canonical bundle.
- A reused key with changed canonical content returns `409 idempotency_key_reused` without writes.
- A reused correlation ID under a different key returns `409 correlation_id_reused` without writes.
- PostgreSQL configuration never silently falls back to memory.
- Alembic is the only durable schema authority; do not call `metadata.create_all()`.
- Database errors and logs must not reveal payload bodies, credentials, or connection strings.
- No cloud deployment, push, paid service, or external delivery is authorized.
- Every production behavior follows a witnessed red, green, refactor cycle.

---

## File Structure

- `src/incident_intel/ingestion.py`: domain records, canonical hashing, conflicts, `IngestionStore`, and the in-memory adapter.
- `src/incident_intel/config.py`: validated environment-backed storage settings.
- `src/incident_intel/db.py`: SQLAlchemy metadata and table definitions shared by migrations and repositories.
- `src/incident_intel/postgres.py`: PostgreSQL engine construction and transactional ingestion adapter.
- `src/incident_intel/api.py`: application factory, store selection, and stable problem-details mapping.
- `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_foundation.py`: authoritative migration history.
- `tests/test_ingestion.py`: in-memory contract and API success behavior.
- `tests/test_config.py`: backend-selection and missing-database configuration behavior.
- `tests/test_api_errors.py`: public conflict and storage-error responses.
- `tests/integration/conftest.py`: disposable-database engine and cleanup fixtures.
- `tests/integration/test_migrations.py`: empty-database upgrade, downgrade, and re-upgrade proof.
- `tests/integration/test_postgres_ingestion.py`: real transaction, duplicate, conflict, rollback, and concurrency proof.
- `compose.yaml`, `.env.example`: reproducible local PostgreSQL service and non-secret configuration contract.
- `.github/workflows/ci.yml`: fast checks plus PostgreSQL migration and integration checks.
- `README.md`, `docs/architecture.md`: truthful setup, data flow, evidence, and limitations.

### Task 1: Define The Ingestion Contract And Conflicts

**Files:**
- Modify: `src/incident_intel/ingestion.py`
- Modify: `tests/test_ingestion.py`

**Interfaces:**
- Produces: `canonical_bundle_json(bundle: EventBundle) -> str`
- Produces: `bundle_payload_hash(bundle: EventBundle) -> str`
- Produces: `IdempotencyConflict`, `CorrelationConflict`, `StorageUnavailable`
- Produces: `IngestionStore.ingest(idempotency_key: str, bundle: EventBundle) -> tuple[IngestionRecord, bool]`
- Preserves: `InMemoryIngestionStore.ingest(...)`

- [ ] **Step 1: Add a failing test for deterministic canonical hashing**

  Add a literal expectation that equivalent validated payloads with reordered JSON object keys
  yield identical canonical JSON and SHA-256 digests. The production change caught is accidental
  hashing of raw request bytes or unordered dictionaries.

- [ ] **Step 2: Run the focused hashing test and verify RED**

  Run: `python -m pytest tests/test_ingestion.py::test_bundle_payload_hash_ignores_json_key_order -v`

  Expected: import failure because `bundle_payload_hash` does not exist.

- [ ] **Step 3: Implement canonical serialization and hashing**

  Use validated model data and deterministic JSON:

  ```python
  def canonical_bundle_json(bundle: EventBundle) -> str:
      return json.dumps(
          bundle.model_dump(mode="json"),
          ensure_ascii=False,
          separators=(",", ":"),
          sort_keys=True,
      )


  def bundle_payload_hash(bundle: EventBundle) -> str:
      payload = canonical_bundle_json(bundle).encode("utf-8")
      return hashlib.sha256(payload).hexdigest()
  ```

- [ ] **Step 4: Run the focused test and verify GREEN**

  Run: `python -m pytest tests/test_ingestion.py::test_bundle_payload_hash_ignores_json_key_order -v`

  Expected: one passing test.

- [ ] **Step 5: Add failing tests for key and correlation conflicts**

  Add tests proving that the in-memory adapter returns a duplicate for the same key and bundle,
  raises `IdempotencyConflict` for the same key with changed validated content, and raises
  `CorrelationConflict` for the same correlation ID under a different key. Use `model_copy` to
  change the synthetic subject without mutating the fixture.

- [ ] **Step 6: Run the focused conflict tests and verify RED**

  Run: `python -m pytest tests/test_ingestion.py -k "conflict or changed_payload" -v`

  Expected: the changed-payload and correlation tests fail because the current dictionary returns
  every repeated key as a duplicate and does not track correlation ownership.

- [ ] **Step 7: Implement the protocol, conflict types, and in-memory semantics**

  Store the hash beside each `IngestionRecord`, keep a `key_by_correlation_id` index, compare hashes
  before returning duplicates, and raise typed domain exceptions without embedding payload data.

- [ ] **Step 8: Run ingestion tests and the full suite**

  Run: `python -m pytest tests/test_ingestion.py -v`
  Then: `python -m pytest`

  Expected: all tests pass.

- [ ] **Step 9: Commit the domain contract**

  ```powershell
  git add -- src/incident_intel/ingestion.py tests/test_ingestion.py
  git commit -m "feat: enforce ingestion conflict semantics"
  ```

### Task 2: Add Validated Settings And Application Injection

**Files:**
- Create: `src/incident_intel/config.py`
- Modify: `src/incident_intel/api.py`
- Create: `tests/test_config.py`
- Create: `tests/test_api_errors.py`
- Modify: `tests/test_ingestion.py`
- Modify: `tests/test_health.py`
- Modify: `tests/test_auth_failures.py`
- Modify: `tests/test_runbook_drafts.py`
- Modify: `tests/test_webhooks.py`

**Interfaces:**
- Consumes: `IngestionStore`, `IdempotencyConflict`, `CorrelationConflict`, `StorageUnavailable`
- Produces: `Settings(storage_backend: Literal["memory", "postgres"], database_url: str | None)`
- Produces: `Settings.from_env(environ: Mapping[str, str] | None = None) -> Settings`
- Produces: `create_app(*, settings: Settings | None = None, ingestion_store: IngestionStore | None = None) -> FastAPI`
- Produces: `ProblemDetail(code: str, detail: str, correlation_id: str | None, retryable: bool)`

`Settings.from_env` reads `INCIDENT_INTEL_STORAGE_BACKEND` and
`INCIDENT_INTEL_DATABASE_URL`; it never infers a backend from whether a URL happens to exist.

- [ ] **Step 1: Write failing settings tests**

  Cover explicit memory mode, PostgreSQL mode with a URL, rejection of a missing backend,
  rejection of PostgreSQL mode without a URL, and rejection of an unknown backend. The tests pass
  a dictionary directly so they do not depend on the developer's machine environment.

- [ ] **Step 2: Run settings tests and verify RED**

  Run: `python -m pytest tests/test_config.py -v`

  Expected: collection fails because `incident_intel.config` does not exist.

- [ ] **Step 3: Implement immutable validated settings**

  Use a frozen dataclass and raise `ValueError` with messages that name missing variable names but
  never echo their values.

- [ ] **Step 4: Run settings tests and verify GREEN**

  Run: `python -m pytest tests/test_config.py -v`

- [ ] **Step 5: Write failing app-factory and error-contract tests**

  Create a fresh app per test with a fresh in-memory store. Assert literal `409` problem bodies for
  both conflict types and literal `503 storage_unavailable` for a store double that raises the
  domain availability error. Do not assert calls on the double; assert the HTTP response.

- [ ] **Step 6: Run focused API tests and verify RED**

  Run: `python -m pytest tests/test_api_errors.py -v`

  Expected: import failure because `create_app` and `ProblemDetail` are absent.

- [ ] **Step 7: Implement `create_app` and exception mapping**

  Move route registration inside the factory or attach routes to the created app through focused
  functions. Remove the process-global `app`; Uvicorn will use
  `uvicorn --factory incident_intel.api:create_app`. When a store is injected, use it directly.
  Without an injected store, select memory only when settings explicitly say memory. PostgreSQL
  store construction is completed in Task 4 before the factory is used in PostgreSQL mode.

- [ ] **Step 8: Update existing API tests to construct isolated apps**

  Replace imports of the module-global `app` with a test fixture or direct
  `create_app(ingestion_store=InMemoryIngestionStore())`. This removes cross-test state leakage.

- [ ] **Step 9: Run focused and full tests**

  Run: `python -m pytest tests/test_config.py tests/test_api_errors.py tests/test_ingestion.py -v`
  Then: `python -m pytest`

- [ ] **Step 10: Commit application construction**

  ```powershell
  git add -- src/incident_intel/config.py src/incident_intel/api.py tests
  git commit -m "refactor: inject incident storage into the API"
  ```

### Task 3: Introduce The Authoritative Migration

**Files:**
- Modify: `pyproject.toml`
- Create: `compose.yaml`
- Create: `.env.example`
- Modify: `.gitignore`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_foundation.py`
- Create: `src/incident_intel/db.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_migrations.py`
- Modify: `src/incident_intel/ingestion.py`
- Delete: `tests/test_postgres_investigation_history.py`

**Interfaces:**
- Produces: `metadata: sqlalchemy.MetaData`
- Produces: `event_ingestions`, `incidents`, `support_tickets`, `evidence_events` SQLAlchemy tables
- Consumes: `INCIDENT_INTEL_TEST_DATABASE_URL` for integration tests

- [ ] **Step 1: Add database dependencies and the disposable PostgreSQL service**

  Add runtime constraints `SQLAlchemy>=2.0,<3`, `psycopg[binary]>=3.2,<4`, and `alembic>=1.13,<2`.
  Pin `postgres:16-alpine` in `compose.yaml`, add a `pg_isready` health check and named development
  volume, and document non-secret local variables in `.env.example`. Install the editable
  development package with `python -m pip install -e ".[dev]"`.

- [ ] **Step 2: Validate and start the disposable database**

  Run: `docker compose --env-file .env.example config`
  Run: `docker compose --env-file .env.example up -d postgres`
  Run: `docker compose --env-file .env.example ps`

  Expected: Compose configuration exits zero and the PostgreSQL service becomes healthy.

- [ ] **Step 3: Write the migration integration test before migration files**

  The test must connect to `INCIDENT_INTEL_TEST_DATABASE_URL`, invoke Alembic programmatically,
  upgrade to `head`, inspect the exact four table names and required indexes, downgrade to `base`,
  confirm the four tables are absent, then upgrade to `head` again.

- [ ] **Step 4: Run the migration test and verify RED**

  With the disposable PostgreSQL service running, run:

  `python -m pytest tests/integration/test_migrations.py -v`

  Expected: failure because `alembic.ini` and the migration revision are absent.

- [ ] **Step 5: Define SQLAlchemy metadata and the Alembic environment**

  Define named primary, unique, foreign-key, and index constraints. `migrations/env.py` reads
  `INCIDENT_INTEL_TEST_DATABASE_URL` first and `INCIDENT_INTEL_DATABASE_URL` second, escapes `%`
  before assigning the URL to Alembic configuration, and uses `metadata` as `target_metadata`.

- [ ] **Step 6: Write migration `0001_foundation` explicitly**

  Use `op.create_table` and `op.create_index` for the four designed tables. The downgrade drops
  indexes and tables in reverse foreign-key order. Do not use autogeneration or `create_all()`.

- [ ] **Step 7: Remove the mock schema helper**

  Delete `PostgresInvestigationHistoryStore` and its fake-cursor tests. The new migration and real
  integration suite become the schema evidence.

- [ ] **Step 8: Run migration verification and full checks**

  Run: `python -m pytest tests/integration/test_migrations.py -v`
  Run: `python -m pytest`
  Run: `python -m ruff check .`

- [ ] **Step 9: Commit the schema foundation**

  ```powershell
  git add -- pyproject.toml compose.yaml .env.example .gitignore alembic.ini migrations src/incident_intel/db.py src/incident_intel/ingestion.py tests
  git commit -m "feat: add migrated incident schema"
  ```

### Task 4: Implement Transactional PostgreSQL Ingestion

**Files:**
- Create: `src/incident_intel/postgres.py`
- Create: `tests/integration/test_postgres_ingestion.py`
- Modify: `src/incident_intel/api.py`

**Interfaces:**
- Consumes: SQLAlchemy tables, `IngestionRecord`, canonical hash, and conflict types
- Produces: `create_engine_from_url(database_url: str) -> Engine`
- Produces: `PostgresIngestionStore(engine: Engine)` implementing `IngestionStore`

- [ ] **Step 1: Write a failing real insertion test**

  Ingest the fixed synthetic authentication fixture, then query all four tables directly and assert
  one receipt, one incident, one ticket, and two evidence rows with literal IDs and values.

- [ ] **Step 2: Run the insertion test and verify RED**

  Run: `python -m pytest tests/integration/test_postgres_ingestion.py::test_ingest_persists_complete_incident_transaction -v`

  Expected: import failure because `PostgresIngestionStore` does not exist.

- [ ] **Step 3: Implement the minimal successful transaction**

  Use `with engine.begin() as connection`, PostgreSQL `INSERT ... ON CONFLICT DO NOTHING RETURNING`,
  parameterized SQLAlchemy statements, generated UUID incident IDs, and the exact stored response
  summary used by the API.

- [ ] **Step 4: Run the insertion test and verify GREEN**

  Run the same focused test and expect one pass.

- [ ] **Step 5: Add failing duplicate and conflict tests**

  Prove same-key/same-hash reread, same-key/different-hash rejection, and different-key/same-
  correlation rejection. Inspect row counts after each conflict to prove no partial writes.

- [ ] **Step 6: Run the conflict tests and verify RED**

  Run: `python -m pytest tests/integration/test_postgres_ingestion.py -k "duplicate or conflict" -v`

- [ ] **Step 7: Implement reread and conflict behavior**

  The losing idempotency insert reads `payload_hash` and `response_summary`; matching hashes return
  the stored record and `duplicate=True`, while different hashes raise `IdempotencyConflict`.
  A losing incident insert raises `CorrelationConflict`, causing the surrounding transaction to
  roll back its new receipt.

- [ ] **Step 8: Add and implement rollback proof**

  First write a test with duplicate synthetic evidence IDs in one bundle. Verify an integrity error
  is translated to a payload-safe domain failure and all four table counts remain zero. Then add
  the minimal exception translation without catching typed conflicts raised intentionally.

- [ ] **Step 9: Add and implement concurrent-ingestion proof**

  Use two threads, a barrier, and independent database connections through the Engine. Submit the
  same key and bundle concurrently. Assert exactly one result has `duplicate=False`, one has
  `duplicate=True`, both return the same literal response, and the database contains one incident.

- [ ] **Step 10: Wire PostgreSQL selection into `create_app`**

  When no store is injected and settings select PostgreSQL, construct the Engine and
  `PostgresIngestionStore`. Memory mode remains explicit. Missing configuration was already rejected
  by Task 2.

- [ ] **Step 11: Run PostgreSQL, API, and full checks**

  Run: `python -m pytest tests/integration/test_postgres_ingestion.py -v`
  Run: `python -m pytest`
  Run: `python -m ruff check .`

- [ ] **Step 12: Commit durable ingestion**

  ```powershell
  git add -- src/incident_intel/postgres.py src/incident_intel/api.py tests/integration/test_postgres_ingestion.py
  git commit -m "feat: persist incident ingestion transactionally"
  ```

### Task 5: Add Reproducible PostgreSQL Runtime And CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Produces: Docker Compose service `postgres`
- Produces: CI PostgreSQL service and integration-test environment

- [ ] **Step 1: Revalidate the Compose boundary before CI and documentation changes**

  Run: `docker compose --env-file .env.example config`

  Expected: exit zero and a resolved PostgreSQL service without undefined variables.

- [ ] **Step 2: Start PostgreSQL and verify readiness**

  Run: `docker compose --env-file .env.example up -d postgres`
  Run: `docker compose --env-file .env.example ps`

  Expected: the `postgres` service reports healthy.

- [ ] **Step 3: Apply, downgrade, and reapply migrations**

  Set both database URL variables to the local disposable database, then run:

  ```powershell
  python -m alembic upgrade head
  python -m alembic downgrade base
  python -m alembic upgrade head
  ```

  Expected: all three commands exit zero.

- [ ] **Step 4: Update CI with PostgreSQL verification**

  Add a PostgreSQL 16 service with a health check. Supply only CI-scoped values, run Alembic upgrade,
  and run the entire suite with integration tests enabled before Ruff.

- [ ] **Step 5: Document the exact local flow and limitations**

  README commands must cover copying `.env.example` to ignored `.env`, starting PostgreSQL,
  migrating, running Uvicorn with PostgreSQL selected, posting the synthetic fixture, repeating it,
  and observing a deliberate conflict. State that workers, authentication, approvals, GPT calls,
  and deployment remain incomplete. Update the architecture document to replace the mock-only
  persistence description.

- [ ] **Step 6: Run the full foundation verification contract**

  Run:

  ```powershell
  python -m pytest
  python -m ruff check .
  git diff --check
  docker compose --env-file .env.example config
  ```

  Then run the documented PostgreSQL-backed API ingestion, duplicate, and conflict requests against
  a locally started process and record the observed HTTP statuses.

- [ ] **Step 7: Scan tracked content for sensitive data**

  Inspect tracked files for key, token, password, private-key, email-address, and known client-name
  patterns. Review matches manually; tests and documentation may contain variable names but no
  populated secrets or real identities.

- [ ] **Step 8: Commit CI and documentation**

  ```powershell
  git add -- .github/workflows/ci.yml README.md docs/architecture.md
  git commit -m "docs: make durable ingestion reproducible"
  ```

### Task 6: Review The Foundation Milestone

**Files:**
- Review: every file changed by Tasks 1 through 5

**Interfaces:**
- Consumes: the approved spec and every verification command above
- Produces: a verified/staged/incomplete milestone report and next-checkpoint handoff

- [ ] **Step 1: Compare the implementation to every specification requirement**

  Build a requirement-to-evidence checklist covering runtime startup, migrations, transaction
  atomicity, duplicate rereads, both conflict types, concurrency, rollback, error redaction,
  integration CI, synthetic-only data, documentation, and deferred items.

- [ ] **Step 2: Run fresh final verification**

  Recreate or clean the disposable database, then rerun migrations, all tests, Ruff, Compose config,
  `git diff --check`, the tracked-content scan, and the documented API smoke flow. Do not reuse
  earlier output for the final claim.

- [ ] **Step 3: Inspect Git history and working tree**

  Run: `git status -sb` and `git log --oneline --decorate -8`.

  Expected: only intentional commits and no uncommitted implementation files.

- [ ] **Step 4: Report exact milestone status**

  Under `Verified`, list only fresh observed results. Under `Staged`, state that commits remain local
  and no push or deployment occurred. Under `Incomplete`, retain every remaining flagship item:
  retrieval, durable worker, authentication, approvals, measured evaluation, observability,
  containerized API/worker, demo, case study, and interview walkthrough.

- [ ] **Step 5: Continue to the next approved flagship milestone**

  The next milestone is incident retrieval and the auditable timeline. Reinspect current state,
  apply the approved overall flagship design, and repeat the design/plan/test/verify discipline
  without pushing or deploying.
