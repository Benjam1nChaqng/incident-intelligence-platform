# Incident Intelligence Platform

Incident Intelligence Platform is a synthetic support-operations backend built to demonstrate
production-minded API and data engineering. It accepts a support ticket plus correlated log
evidence, commits the complete incident to PostgreSQL in one transaction, and gives callers stable
idempotency and conflict behavior.

No real employer, customer, school, account, ticket, or log data belongs in this repository.

## What the current foundation proves

- Strict Pydantic validation for synthetic tickets and evidence events.
- Deterministic SHA-256 hashing of validated JSON, independent of object key order.
- Transactional PostgreSQL persistence across receipts, incidents, tickets, and evidence.
- `201` for a new request, `200` for an exact duplicate, and stable `409` responses for key or
  correlation conflicts.
- Database-enforced concurrency: two simultaneous copies produce one accepted write and one
  duplicate response.
- Full rollback when any related ticket or evidence row violates a storage constraint.
- Alembic-owned upgrade and downgrade history, plus PostgreSQL-backed CI tests.
- Deterministic authentication-failure evidence and runbook-draft previews that remain behind a
  human approval boundary.

## Durable local quick start

Requirements: Python 3.11 or newer and Docker with Compose support.

```powershell
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
docker compose --env-file .env up -d postgres

$env:INCIDENT_INTEL_STORAGE_BACKEND = "postgres"
$env:INCIDENT_INTEL_DATABASE_URL = "postgresql+psycopg://incident_intel:local-development-only@localhost:54329/incident_intel"
$env:INCIDENT_INTEL_TEST_DATABASE_URL = $env:INCIDENT_INTEL_DATABASE_URL

python -m alembic upgrade head
python -m uvicorn incident_intel.api:create_app --factory --reload
```

The values in `.env.example` are local-development-only placeholders. Use different credentials
outside a disposable local environment and never commit a populated `.env` file.

## Reproducible ingestion demo

In a second PowerShell window, post the fixed synthetic fixture:

```powershell
$uri = "http://localhost:8000/events"
$headers = @{ "Idempotency-Key" = "demo-auth-failure-001" }
$fixture = Get-Content .\tests\fixtures\auth_failure_bundle.json -Raw

$accepted = Invoke-WebRequest -Method Post -Uri $uri -Headers $headers `
  -ContentType "application/json" -Body $fixture
$accepted.StatusCode
```

The first response is `201`. Repeat the same request to prove safe retry behavior:

```powershell
$duplicate = Invoke-WebRequest -Method Post -Uri $uri -Headers $headers `
  -ContentType "application/json" -Body $fixture
$duplicate.StatusCode
$duplicate.Content
```

The duplicate response is `200` with `"duplicate": true`. Now reuse the key with changed content:

```powershell
$changed = $fixture | ConvertFrom-Json
$changed.ticket.subject = "Changed synthetic subject for the conflict demo"
$changedBody = $changed | ConvertTo-Json -Depth 20

try {
  Invoke-WebRequest -Method Post -Uri $uri -Headers $headers `
    -ContentType "application/json" -Body $changedBody
} catch {
  $_.Exception.Response.StatusCode.value__
}
```

The deliberate conflict is `409`, and the original incident remains unchanged.

## Verification

With PostgreSQL running and `INCIDENT_INTEL_TEST_DATABASE_URL` set:

```powershell
python -m alembic downgrade base
python -m alembic upgrade head
python -m pytest
python -m ruff check .
git diff --check
```

Integration tests skip when the test database variable is absent. Unit and API tests still run.
For an explicitly non-durable development process, set
`INCIDENT_INTEL_STORAGE_BACKEND=memory`; the application never silently falls back to memory.

## Honest limitations

The durable ingestion foundation is implemented. Background workers, authentication and
authorization, persisted classification and approval decisions, real outbound delivery, optional
GPT evaluation, production deployment, and operational dashboards are not implemented yet. The
preview endpoints do not send messages or update external systems.

See [docs/architecture.md](docs/architecture.md) for the transaction and schema boundaries.
