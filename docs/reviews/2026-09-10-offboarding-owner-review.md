# Technical owner review: synthetic offboarding lab

Reviewed September 10, 2026 by the portfolio owner with an independent code reviewer.
Handoff: `gap-1485ed30cb95e41e`. Baseline HEAD: `10338170146615deaa60ea9be20a33d3b896a792`.

## Decision

Accepted for local portfolio integration as an offline synthetic exercise. No code fix was required.
The user assigned ownership of daily portfolio builds to this task on September 10. This is delegated
technical review, not a claim that Benji performed a real tenant lab or approved new resume wording.

The adapter models one disabled synthetic identity, a later access observation, and one linked
endpoint. It produces the existing EventBundle contract without a new route or storage behavior.
Exact duplicate events collapse; conflicting duplicates, missing identities, unrelated endpoint
links, and access at or before disablement are rejected. UTC normalization and deterministic ordering
preserve the ingestion payload hash. The API test proves 201 then 200 replay for one incident and
ticket with two linked logs using in-process memory transport.

## Reviewed bytes

| File | SHA-256 |
| --- | --- |
| `src/incident_intel/offboarding.py` | `6e53d9a40275547fd37d0c1912624d0473d140f25df6ecf21be7869ca4f9683a` |
| `tests/test_offboarding.py` | `59e26a7a7f6c5e3de44d04001a86f588bfc2061076ffd5d3bbc0d2c43630f70f` |
| `tests/fixtures/google_workspace_offboarding.json` | `58b2709008a48f7a9ff9c1824d326633e4d943d124767e0a8b37efe6add1eb38` |
| `tests/fixtures/google_workspace_offboarding.verification.md` | `a8cd3cc8f797bb5e4fc92bdeed775b0e7ff58a78e2c285b881d0800657f10078` |

Recheck hashes before reusing this decision. Changed bytes require a new review. The historical
verification file is retained unchanged; this document supersedes only its pending-owner-review note.

## Fresh verification

From `C:\Users\bchang\Projects\incident-intelligence-platform`:

- `python -m pytest tests/test_offboarding.py -q`: 24 passed in 3.08 seconds.
- `python -m pytest -q`: 110 passed, 28 skipped in 20.83 seconds. PostgreSQL tests skipped because
  the test database environment variable was absent; this result does not verify PostgreSQL.
- `python -m ruff check .`: all checks passed.
- `git diff --check`: passed.

Full current release database verification is tracked separately in the finish plan.

## Claim boundary and handoff state

This fixture is an invented offline format. It proves no Google API compatibility, live account
behavior, certification, real tenant administration, or production experience. No resume was edited.
`resumeClaimEligible` and `productionExperienceVerified` remain false. Vendor access remains unverified.

The source handoff CLI supports worker progress and unverified evidence only. Its documentation puts
owner review outside the CLI, so this document closes the technical review without forging a completed
CLI status or mutating claim flags. The source state and historical blocked events stay unchanged.
Its stale blocked status does not authorize rebuilding the accepted lab or opening a second handoff.
No private application or contact data is copied into this review.
