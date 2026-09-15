# Webhook preview idempotency correction, September 15, 2026

Reusing an idempotency key with a different webhook destination, event type or payload previously
returned `200` and the earlier receipt as if the changed request had succeeded. The corrected
preview returns `409` with the existing `idempotency_key_reused` problem code. An exact replay
still returns `200`; first requests still return `201`. Conflicts do not replace the original
receipt, attempt count, status or retry delay. No webhook is sent.

## Design and compatibility

| Decision | Evidence and tradeoff | Verification |
| --- | --- | --- |
| Bind a key to the complete validated request using a canonical SHA-256 fingerprint | Existing code checked only the key. Stable JSON key ordering avoids false conflicts. One hash per receipt adds small process-local storage; the request body is not retained by the store. | Destination, event-type and payload conflicts; equivalent key ordering; replay after rejection. |
| Make lookup, identity comparison and receipt storage one locked operation | The synchronous API can serve requests concurrently. A single store lock prevents competing writers from pairing one request's identity with another receipt. Hashing happens before the short critical section. | Eight concurrent calls with two different requests produce one winning receipt, its three duplicates and four conflicts. |
| Return copies of stored records | A caller could mutate the original returned object and corrupt later receipts. | Mutation of the first returned record does not change an identical replay. |
| Preserve the preview boundary | This is an in-memory synthetic feature, not external delivery or durable webhook processing. No schema, dependency, authentication or deployment change is required. | Existing happy-path and retry-status tests, full project suite and documented process/restart limitation. |

Callers that previously depended on changed requests being silently accepted now receive a
nonretryable conflict and must use a new key. HTTP 409 is also declared in the route's OpenAPI
responses. The existing conflict counter increments; the response does not expose the earlier
stored request. Durable or multi-process webhook handling remains deferred until explicitly scoped.

## Verified locally

Baseline: clean `main` at `23230b0f1bf70221c66374efb13328cb3ea2eaab`, matching the configured GitHub
remote. Its existing CI was separately confirmed green for that exact old revision; it is not
evidence for this change.

- Before the implementation, the expanded webhook suite produced **8 failures and 5 passes**.
  The API regressions observed `200` where `409` was required, and direct-store, concurrency and
  mutation tests exposed the related receipt-integrity failures.
- `python -m pytest tests/test_webhooks.py -q`: **13 passed** after the correction.
- Full local verification ran from **17:33:37 to 17:34:18 UTC on September 15**:
  `python -m alembic upgrade head`, `python -m pytest -q`, `python -m ruff check .`, and
  `git diff --check` all exited zero. **147 tests passed, zero skips**. Nine new parametrized
  regression cases explain the increase from 138 tests.
- PostgreSQL **16.14** used the already cached image with pulling disabled, a new uniquely named
  container, loopback-only random port, fresh tmpfs data, and zero initial public tables.
  Ephemeral credentials stayed in process memory/stdin; inherited database settings were removed
  from the child environment. Only the returned container ID was removed, and its absence verified.
- Independent read-only review found no blocking issue. The concurrency test exercises contention
  and the observable one-winner invariant; it is not a deterministic scheduler or a throughput test.

The original four synthetic offboarding artifact hashes still match their accepted review.
No client data, live tenant, resume changes, package installation or production deployment was used.
The human interview rehearsal remains unassessed. Remote publication and CI must be verified for
the actual pushed SHA; they are recorded separately in the daily owner's local checkpoint and
GitHub Actions rather than inferred from these local checks.
