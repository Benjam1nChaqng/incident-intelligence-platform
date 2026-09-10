# Synthetic Offboarding Checkpoint Verification

Verified locally on 2026-09-04 (America/Los_Angeles).
Handoff: `gap-1485ed30cb95e41e`, selected gap: Google Workspace.
Status: implementation and local verification complete; owner evidence submission pending.
The resume-builder handoff/state was read only and was not updated by this checkpoint.

## Scope And Files

- Adapter: `src/incident_intel/offboarding.py`, entry point `adapt_offboarding_fixture(payload)`.
- Fixture: `tests/fixtures/google_workspace_offboarding.json`.
- Tests: `tests/test_offboarding.py`.
- Evidence: this file. These four new files are the entire checkpoint change.

The fixture explicitly uses an invented offline format, not a vendor API schema. It models
`synthetic-user-offboarding-001` disabled at `2026-09-04T10:00:00Z`, followed by an allowed
access observation at `2026-09-04T10:05:00Z`, linked to `synthetic-endpoint-001`.
The adapter emits two existing `LogEvent` records in `EventBundle` `INC-OFFBOARD-001`
with ticket `TCK-OFFBOARD-001`; the access cites disablement event `GW-DISABLED-001`.
"Allowed after disabled" is an invented incident signal, not a claim about Google behavior.

IDs are preserved, timestamps normalized to UTC, and access events sorted by time and ID.
Exact duplicate access events collapse before bundle validation; conflicting duplicates,
missing identities, unrelated endpoint/identity links, and access at or before disablement fail.
The API test uses in-process HTTP transport and the existing in-memory ingestion store:
first submission returns 201, replay returns 200 with the same incident/ticket and two logs.
No new route, EventBundle contract, storage behavior, dependency, or UI was added.

## Exact Verification Commands And Results

Working directory for every command: `C:\Users\bchang\Projects\incident-intelligence-platform`.
Runtime: Windows, Python 3.12.10, pytest 9.0.3.
Output below contains exact result excerpts, not full tracebacks or per-test listings.

Test-first behavioral check, before implementing the mapping:

```text
python -m pytest tests/test_offboarding.py -q -x
E       NotImplementedError: Synthetic offboarding mapping is not implemented
1 failed in 1.25s
Exit code: 1 (expected before implementation)
```

Final focused suite, after implementation and formatting:

```text
python -m pytest tests/test_offboarding.py -q
24 passed in 2.08s
Exit code: 0
```

Final full existing suite plus the new tests:

```text
python -m pytest
collected 138 items
====================== 110 passed, 28 skipped in 18.72s =======================
Exit code: 0
```

All 28 skips are existing PostgreSQL integration tests. Their reported reason is
`INCIDENT_INTEL_TEST_DATABASE_URL is required for integration tests`.
No database was configured or contacted for this checkpoint. Baseline before this slice was
86 passed and 28 skipped; all 24 added tests pass.

```text
python -m ruff check .
All checks passed!
Exit code: 0
```

Git HEAD at final verification: `10338170146615deaa60ea9be20a33d3b896a792`, branch `main`.
During initial inspection, external work advanced HEAD from
`a23d0ef2a2a20f7e5305344ab823a520ba8d8fbd`; the updated contracts were reread before edits.
Existing tracked files were left unchanged. No commit, push, or deployment was performed.

## Limits And Next Lab Prerequisite

This proves only a deterministic local simulation. No Google, Okta, Jamf, or Slack tenant
was contacted; no credentials, client data, account settings, applications, automations,
or resume claims were modified. It establishes neither vendor API compatibility nor
production administration, certification, or resume-claim eligibility. The input validator
is not a general-purpose personal-data scrubber.

Before a real-world lab: obtain explicit owner authorization and access to an isolated
Google Workspace test tenant with disposable test identities and a test endpoint. Agree on
least-privilege access and a cleanup/recovery procedure, verify current official documentation,
then collect sanitized real audit evidence to validate actual fields and offboarding behavior.
Tenant access and vendor behavior remain unverified; no signup or purchase is part of this work.
