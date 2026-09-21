# Ticket tag validation correction, September 20, 2026 Pacific

The ticket validator converted every supplied tag value with `tuple(value)`. A string was
silently split into characters, an object became its keys, and a number raised an uncaught
`TypeError`, returning HTTP 500. Invalid strings and objects could be accepted and consume an
idempotency key before the caller corrected the request.

The validator now only normalizes `None` to an empty tuple. Pydantic's existing typed-tuple
validation checks every other input and converts valid string arrays. Omitted tags, `null`,
empty arrays, and populated string arrays retain their existing behavior. Invalid JSON shapes
return HTTP 422 with the `body.ticket.tags` location before either storage backend is called.
There is no dependency, database schema, authentication or deployment change.

## Verified evidence

Baseline: clean `main` at `b5ac0714f87ec05cd12d021bbbb5c7f0583eef22`, matching remote `main`.

- Before the fix, `python -m pytest tests/test_schemas.py tests/test_api_errors.py -q --tb=short`
  produced **8 failures and 14 passes**. The API cases observed two wrong 201 responses and a 500.
- After the fix, the same two test files passed **22 tests**. Regression coverage checks invalid
  scalar/object shapes, compatible empty/list inputs, no stored receipt after rejection, and a
  corrected request returning 201 followed by an exact replay returning 200 with the same key.
- Full checks ran at **03:03:06-03:04:14 UTC on September 21** (September 20 Pacific):
  `python -m alembic upgrade head`, `python -m pytest -q`, `python -m ruff check .`, and
  `git diff --check` passed. **162 tests passed with zero skips**, including PostgreSQL integration.
- The existing verification helper used a fresh PostgreSQL 16.14 container from a cached image,
  with no image pull, an isolated loopback port, tmpfs data and zero initial public tables.
  Inherited database settings were removed from the child environment. Only the created
  container was removed; its absence was verified. Ephemeral secrets were not saved to logs.
- Final source/test diff and tag consumers were reviewed. The four accepted synthetic
  offboarding hashes still match, and both resume claim flags remain false.

All data is synthetic. Local checks establish the behavior above; publication and remote CI
must match the actual pushed revision and are recorded in the daily owner's local checkpoint.
