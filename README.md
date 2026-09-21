# Incident Intelligence Platform

Incident Intelligence Platform is a synthetic support-operations backend built to demonstrate
production-minded backend, platform, and applied-AI engineering. It accepts a support ticket plus
log evidence, persists the incident atomically, classifies it in a durable worker, and keeps every
draft behind an authenticated human approval decision.

No real employer, customer, school, account, ticket, or log data belongs in this repository. The
project performs no external delivery and makes no paid model calls.

## What it proves

- Transactional PostgreSQL ingestion across idempotency receipts, incidents, tickets, and evidence.
- Stable retry semantics: `201` accepted, `200` exact duplicate, and `409` changed-payload or
  identity conflicts.
- Database-enforced concurrency for both ingestion and `FOR UPDATE SKIP LOCKED` worker claims.
- Cursor-paginated incident timelines with stable filters and ordered cited evidence.
- A deterministic classifier with versioned synthetic evaluation data and reproducible metrics.
- Durable jobs with expiring ownership leases, stale-worker fencing, retry backoff, terminal
  failure, and replay-safe completion.
- Short-lived HMAC-signed synthetic viewer, operator, and admin identities.
- Persisted response drafts that can transition only once through an operator approval or rejection.
- Privacy-safe JSON request logs, operation counters, and separate liveness and database readiness.
- A non-root container image plus API, worker, migration, and PostgreSQL Compose services.

## Container quick start

Requirements: Docker with Compose support, Python 3.12+, and PowerShell 7. Run these commands from
the repository root in one terminal. The local demo below reuses the secret created here.

```powershell
Copy-Item .env.example .env
$env:INCIDENT_INTEL_TOKEN_SECRET = [Convert]::ToBase64String(
    [Security.Cryptography.RandomNumberGenerator]::GetBytes(48)
)
(Get-Content .env) -replace '^INCIDENT_INTEL_TOKEN_SECRET=.*$',
    "INCIDENT_INTEL_TOKEN_SECRET=$env:INCIDENT_INTEL_TOKEN_SECRET" | Set-Content .env

docker compose --env-file .env up --build --detach
docker compose --env-file .env ps
```

The migration service must finish before the API and worker start. The API is ready when
`http://localhost:8000/readyz` returns a response with `status` equal to `ready`. The image runs as an
unprivileged `app` user. The token-secret placeholder in `.env.example` is intentionally empty;
startup requires your generated value. Other values are disposable local placeholders. Never
commit `.env`. Both published ports bind to `127.0.0.1`.

This release assumes trusted local callers. `POST /events` and preview routes accept unauthenticated
synthetic input; ingestion authentication, rate limiting, TLS, and enterprise identity integration
are prerequisites for any network exposure. Protected investigation and approval routes enforce
signed roles even in the local demo.

## Run the deterministic demo

Install the project locally so the script can run migrations and issue demo tokens:

```powershell
python -m pip install -e ".[dev]"
$env:INCIDENT_INTEL_DATABASE_URL =
    "postgresql+psycopg://incident_intel:local-development-only@localhost:54329/incident_intel"
./scripts/demo.ps1
```

The script uses fresh GUID-based synthetic identifiers, accepts only a loopback base URL, and
does not print tokens. Clear `INCIDENT_INTEL_TEST_DATABASE_URL` before the demo; conflicting
database targets are rejected before migration. It stops on any failed native command or assertion.
It checks exact `201`,
`200`, and `409` responses, the conflict code, original ticket preservation, ordered evidence
content, a persisted classification and its citations, the initial `pending_review` draft, and the
final stored `approved` decision from the named operator. Repeated runs leave separate synthetic
incidents in the local database. The API and worker must be running and ready first.

## API and roles

| Endpoint | Minimum role | Purpose |
| --- | --- | --- |
| `GET /healthz`, `GET /readyz`, `GET /metrics` | Public local operations | Process, database, and metrics evidence |
| `POST /events` | Public, trusted loopback | Atomically ingest a synthetic event bundle |
| `POST /webhooks/deliveries/preview` | Public, trusted loopback | Preview a process-local synthetic delivery receipt |
| `GET /incidents`, `GET /incidents/{id}` | Viewer | Retrieve paginated incidents and timelines |
| `POST /incidents/{id}/classifications` | Operator | Enqueue a durable classification job |
| `GET /jobs/{id}` | Viewer | Inspect job state and failure class |
| `GET /classifications/{id}` | Viewer | Retrieve the saved result, evidence citations, and provenance |
| `POST /jobs/{id}/retry` | Admin | Explicitly requeue a terminally failed job |
| `POST /incidents/{id}/drafts` | Operator | Create a deterministic pending draft |
| `GET /drafts/{id}` | Viewer | Review draft and decision state |
| `POST /drafts/{id}/approve`, `POST /drafts/{id}/reject` | Operator | Record one final human decision |

The webhook preview requires an `Idempotency-Key`. The first request returns `201`; an identical
destination, event type and payload replay returns `200` with the original delivery receipt.
Reusing that key with any of those fields changed returns `409` / `idempotency_key_reused` and
leaves the original receipt intact. Use a new key for a different request. JSON object key order
does not change request identity. The preview never sends a webhook; its receipts exist only
within one application process and are lost on restart, including when PostgreSQL is configured.
See the [idempotency regression verification](docs/verification-2026-09-15-webhook-idempotency.md).

The explicitly selected in-memory event store serializes concurrent calls within one store
instance, preserving the same duplicate and conflict rules as sequential requests. Its data is
lost on restart and is not shared between application processes; use PostgreSQL for durable,
multi-process ingestion. See the
[overlapping-ingestion verification](docs/verification-2026-09-16-ingestion-concurrency.md).

Ticket `tags` must be an array of strings. Omitted tags, `null`, and `[]` mean no tags.
Other JSON shapes return `422` before ingestion, so a corrected request can reuse its
idempotency key. See the [tag validation regression](docs/verification-2026-09-20-ticket-tags.md).

Capture a 15-minute local token after setting `INCIDENT_INTEL_TOKEN_SECRET`; do not paste it into
logs, screenshots, or the repository:

```powershell
$viewerToken = python -m incident_intel.token --role viewer --operator-id synthetic-demo-viewer
$operatorToken = python -m incident_intel.token --role operator --operator-id synthetic-demo-operator
```

## Measured deterministic evaluation

```powershell
python -m incident_intel.evaluate `
    --dataset data/evaluation_v1.json `
    --output artifacts/evaluation-rules-v1.json
```

The checked-in September 4, 2026 run contains 12 curated synthetic cases across four categories.
It measured macro F1 `1.0`, citation validity `1.0`, abstention rate `0.25`, unsupported-evidence
rate `0.0`, median latency `0.0302 ms`, and p95 latency `0.2161 ms`. Citation validity checks
existing IDs and requires a nonempty citation set for non-abstaining predictions; it does not
measure whether the evidence logically supports the explanation. This small designed dataset
proves repeatability and contract behavior, not real-world generalization.

## Verification

The [portfolio owner](docs/PORTFOLIO-OWNER.md) follows a finite
[finish checklist](docs/superpowers/plans/2026-09-10-portfolio-finish.md). The
[September 10 verification](docs/verification-2026-09-10-owner.md) passed **138 tests with zero
skips** against a fresh PostgreSQL 16.14 database, including the reviewed
[synthetic offboarding lab](docs/reviews/2026-09-10-offboarding-owner-review.md).
The [published release CI](https://github.com/Benjam1nChaqng/incident-intelligence-platform/actions/runs/34514582082)
passed all 138 tests with zero skips and rehearsed standard Docker Compose startup plus the full
deterministic demo at revision `d4420f21a3e6cb0942ef62944db5bc298dffe626`.

Use a disposable PostgreSQL 16 test database: integration tests create and drop schema objects.
Set `INCIDENT_INTEL_TEST_DATABASE_URL` to that database, then run:

```powershell
python -m pytest
python -m ruff check .
git diff --check
docker build -t incident-intelligence-platform:local .
```

Integration tests skip when the test database variable is absent. The application never silently
falls back to memory; a backend must be selected explicitly. PostgreSQL runtime configuration also
requires a local token secret.

The final verification record is maintained in the [case study](docs/case-study.md). The September 4
suite passed all 114 then-existing tests against PostgreSQL 16, including migrations and contention checks.
The September 10 GitHub run verifies the published revision's standard Docker Compose startup on
Ubuntu. This Windows/WSL host still uses the documented [Podman fallback](docs/local-verification.md);
its September 4 packaged demo and outage/recovery evidence remains distinct from the remote run.
See the [publication record](docs/verification-2026-09-10-publication.md) for exact results and boundaries.

## Honest limitations

- The classifier is deterministic. No GPT comparison is published and no model cost is claimed.
- The evaluation set is small, curated, synthetic, and designed to exercise known rules.
- HMAC tokens demonstrate authorization boundaries; they are not an enterprise identity provider.
- Metrics are process-local and reset on restart. API `/metrics` does not aggregate the separate
  worker's counters; there is no external dashboard or alerting.
- There is no browser UI, real customer data, outbound connector, cloud deployment, or production
  user traffic.

See [the architecture](docs/architecture.md) and [the case study](docs/case-study.md) for the design
tradeoffs, measured evidence, and interview walkthrough.
