# In-memory ingestion concurrency correction, September 16, 2026

Overlapping event requests could observe a receipt before its payload hash was written, causing
an unexpected `KeyError` instead of returning a duplicate or identity conflict. A different key
could also claim the same correlation ID before the first request populated that index. These
failures affected the explicitly selected in-memory backend; PostgreSQL ingestion is unchanged.

## Change and scope

A lock per store instance now covers receipt lookup, both conflict checks, and all three index
writes. Canonical payload hashing happens before the lock, keeping the critical section short.
Successful replays still return the original immutable receipt. Changed payloads and competing
correlation IDs still raise the existing domain conflicts, which the API maps to HTTP 409.

The lock coordinates threads using one store. It does not persist data, coordinate separate
processes, or protect callers that directly mutate the store's internal dictionaries. All
application ingestion accesses use `ingest`; no API, dependency, schema, or deployment changes
were required. PostgreSQL remains the durable multi-process backend.

## Verification

Baseline: clean `main` at `d8fb18c328f4a73186c88a92c6d22166530c3c3f`, matching the configured
GitHub remote before this contribution.

- Three new regression cases pause the first request immediately after its receipt write and
  start a contender before releasing it. They cover identical retries, changed payloads with
  the same key, and the same correlation ID with another key. Each checks the surviving receipt,
  hash and correlation mappings and a later exact retry.
- Before the fix, `python -m pytest tests/test_ingestion.py -q -k overlapping` produced
  **3 failures**: two `KeyError` failures and one wrongly accepted correlation conflict.
- After the fix, `python -m pytest tests/test_ingestion.py -q` passed **11 tests**.
- The controlled write pause gives the competing thread a bounded 250 ms opportunity to run;
  this is a regression reproduction, not a scheduler guarantee or performance measurement.
- Full local verification ran from **16:01:06 to 16:01:46 UTC on September 16**.
  `python -m alembic upgrade head`, `python -m pytest -q`, `python -m ruff check .`, and
  `git diff --check` all exited zero. **150 tests passed, zero skips**.
- Tests used a fresh disposable PostgreSQL **16.14** container from the cached image with
  pulling disabled, an isolated loopback port, tmpfs data, and zero initial public tables.
  Inherited database settings were removed from the child environment. Ephemeral secrets
  stayed in process memory/stdin. Only the created container was removed and its absence checked.

The accepted four offboarding artifact hashes still match. All fixtures are synthetic. The
source diff and all ingestion-store usages were reviewed for consistency; no other application
code accesses its dictionaries. Exact pushed-SHA and remote CI results belong in the local daily
checkpoint and GitHub Actions after publication, separate from this local verification record.
