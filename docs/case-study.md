# Case Study: Incident Intelligence Platform

## The career signal

This project demonstrates backend design under failure: atomic multi-table writes,
database-owned concurrency, durable
background work, evidence-grounded classification, authorization, human approval, reversible
schema changes, privacy-safe operations, and measured verification.

It is relevant to backend, platform, developer tooling, systems, and applied-AI engineering roles.

## Problem

Support automation receives duplicate deliveries, partially correlated evidence, transient worker
failures, and generated text that should never take action by itself. The design needed to answer
four questions clearly:

1. Can a caller retry without creating duplicate incidents?
2. Can two API or worker processes race without application-level guesswork?
3. Can every classification cite persisted evidence and survive a restart?
4. Can a generated draft become approved without a named human decision?

## Solution

The API validates an event bundle and commits its receipt, incident, ticket, and logs in one
PostgreSQL transaction. Database constraints select concurrent winners. Incident retrieval uses
stable cursor positions. A durable job table separates request acceptance from classification;
workers use `FOR UPDATE SKIP LOCKED`, bounded batches, expiring claim leases, exponential backoff,
and idempotent completion. A unique attempt token prevents a stale worker from overwriting a newer
claim. Classifications retain evidence IDs and version metadata. Drafts start pending and
require a short-lived signed operator or admin identity to record one final decision.

The system is containerized as separate migration, API, worker, and PostgreSQL services. It emits
bounded JSON request logs, operation counters, and independent health and database readiness.

## Measured evidence

### September 10 owner closeout

The [current verification record](verification-2026-09-10-owner.md) reports **138 passed, zero skips,
in 23.86 seconds** against a newly created PostgreSQL 16.14 database. Empty-schema migrations,
Ruff, whitespace checks, and removal of only the new disposable container passed. This includes
24 tests for the [reviewed synthetic offboarding lab](reviews/2026-09-10-offboarding-owner-review.md),
an invented offline fixture format mapped into the existing EventBundle contract. It establishes
no vendor API compatibility, live tenant operation, or production administration experience.

The [owner runbook](PORTFOLIO-OWNER.md) and [finish checklist](superpowers/plans/2026-09-10-portfolio-finish.md)
freeze new features and separate local completion from public closeout. The existing daily automation
now resumes the single owner task at 7:00 PM Pacific. After Benji approved publication, revision
`d4420f21a3e6cb0942ef62944db5bc298dffe626` was pushed and its
[GitHub CI run](https://github.com/Benjam1nChaqng/incident-intelligence-platform/actions/runs/34514582082)
passed 138 tests with no skips in 4.59 seconds. Migration, lint, image build, standard Compose
startup, readiness, the existing assertion-driven demo, and isolated cleanup all passed.
Its Ubuntu/PowerShell route follows the
[GitHub Actions documentation](https://docs.github.com/en/actions/tutorials/build-and-test-code/powershell).
The [publication record](verification-2026-09-10-publication.md) captures exact results. This verifies
the technical release; no production deployment, live vendor experience, or human rehearsal is implied.

### September 4 packaged runtime evidence

September 4, 2026 local verification used Windows PowerShell 7, Python 3.12, and PostgreSQL 16 in
rootful Podman on WSL. The final automated suite passed **114 tests, zero skips, in 42.22 seconds**
with the PostgreSQL runtime and test URLs configured. Ruff and the whitespace diff check passed.
Migration coverage includes a complete downgrade to an empty schema, an upgrade through the
previous revision 0003, and an upgrade to 0004 with its new claim-ownership column and foreign key.

The packaged API and worker completed two assertion-driven demonstrations around a database
restart. Both proved `201` ingestion, `200` exact retry, `409` changed-payload conflict, preserved
evidence, a persisted authentication classification with citations, and a recorded approval.
Readiness changed `200 -> 503 -> 200` when the database stopped and restarted; the worker survived
and processed the second incident. These are targeted failure checks, not a throughput benchmark.
Final database counts were two incidents, two classifications, and two approval decisions. Captured
API and worker logs emitted structured events and contained none of the generated credentials,
Bearer-token text, or authorization-header text. The final-image rehearsal repeated these checks.

The final Docker-format image is
`4734c1abca4cb8a5c8de6582fd1fd3e01eb0771b000dfeec1666206aec36d3a9` and runs as the
unprivileged `app` user (UID 100). The supplied Compose file validates, and
fresh database initialization and all four services passed staged startup with explicit database
health, migration exit, and API readiness gates. This host lacks Podman health timers and its
Compose provider fails nested one-shot dependencies. Consequently, ordinary one-command Docker
Compose startup was **staged, not verified at that checkpoint**. The repeatable
[local verification procedure](local-verification.md) records the working fallback without
changing operating-system settings. Remote CI had not run at that checkpoint because the release
had not yet been pushed; the September 10 remote evidence above supersedes that publication status.

An independent code review led to regression coverage for unique per-attempt ownership, service
authorization, consistent approval reads, runtime logging, and demo database-target selection.
A targeted privacy scan of 71 release candidates found no suspicious credential formats, phone
numbers, or named private-organization matches; reviewed matches were synthetic placeholders and
reserved example addresses. This is a scoped scan, not a guarantee against every possible secret.

The checked-in deterministic evaluation report contains 12 curated synthetic cases with macro F1
`1.0`, citation validity `1.0`, abstention `0.25`, unsupported evidence `0.0`, median latency
`0.0302 ms`, and p95 `0.2161 ms` at `2026-09-04T23:55:00Z`.

The classifier numbers describe this designed dataset only. They are not evidence of production
accuracy, model generalization, real users, or cost savings. The citation and unsupported-evidence
checks measure existing evidence IDs and require nonempty citations for a non-abstaining result.
They do not establish semantic support for a generated explanation. Regression tests explicitly
reject uncited predictions and invented IDs while permitting empty citations for abstention.

## Release acceptance map

| # | Acceptance check | Status | Evidence or boundary |
| ---: | --- | --- | --- |
| 1 | Clean start for API, worker, and PostgreSQL | Verified | September 10 GitHub run passed standard Compose startup and the full demo; September 4 separately verified the Podman fallback. |
| 2 | Empty-database migrations | Verified | Full reversal, previous-revision upgrade, and new claim-token/FK checks against PostgreSQL. |
| 3 | Duplicate, conflict, concurrency, retry, approval invariants | Verified September 10 | 138-test suite includes real concurrent claims/decisions, lease expiry, stale-worker fencing, replay, admin retry, and the offline offboarding fixture. |
| 4 | Reproducible deterministic evaluation | Verified | Versioned dataset, command, checked-in JSON report, and metric tests. |
| 5 | Published GPT comparison is measured | Not applicable | No GPT result or cost claim is published. |
| 6 | Drafts cannot bypass approval | Verified | API and service role checks, row lock, state constraint, and a unique persisted decision. |
| 7 | CI, image, and demo | Verified | Exact published revision d4420f2 passed GitHub tests/lint, image build, Compose startup, and demo. September 4 local evidence separately covers database recovery. |
| 8 | Synthetic fixtures and privacy scan | Verified within scan scope | 71-file targeted scan and tested body/token exclusion from request logs. |
| 9 | Honest case study | Verified | Records measured results, test environment, startup limitation, and explicit future work. |
| 10 | Short interview explanation | Staged for Benji | Walkthrough and questions prepared. Benji's own explanation and recall have not been assessed. |

The technical portfolio release is published and verified, including standard Docker startup.
Benji's own interview rehearsal remains unassessed; it is the only remaining human closeout item.
No production service has been deployed. New deployment or feature scope still needs separate authorization.

## Ninety-second interview walkthrough

“I built a synthetic incident-intelligence backend to demonstrate the failure modes hidden by a
normal CRUD demo. An event bundle is validated and hashed, then PostgreSQL commits the idempotency
receipt, incident, ticket, and evidence together. The database picks the winner during concurrent
retries, so identical content returns the original response while changed content conflicts.

“Classification runs outside the request in a durable outbox worker. Workers claim rows with
`SKIP LOCKED`, recover expired leases, reject stale claim tokens, retry transient failures with
bounded exponential backoff, and write the result plus job completion atomically so replay cannot
duplicate a classification. The deterministic baseline
cites exact stored evidence and has a reproducible synthetic evaluation report.

“Generated response drafts cannot approve themselves. Short-lived signed local identities enforce
viewer and operator permissions, and a row lock plus unique decision record allows exactly one
human approval or rejection. The verification suite targets PostgreSQL concurrency, reversible
migrations, logging redaction, and a live demo that checks each response. The case study records
which checks were actually run. I do not claim production traffic or real-world classifier accuracy.”

## Interview questions to prepare

- Why is the idempotency receipt inserted before child records, and why is it in the same
  transaction?
- What failure occurs if a worker marks a job complete before storing its result?
- Why does `SKIP LOCKED` help throughput, and what starvation or recovery concerns remain?
- How does the opaque cursor prevent page overlap when timestamps match?
- Why are cited evidence IDs more useful than an explanation string alone?
- What would change when replacing local HMAC identities with OIDC and an enterprise identity
  provider?
- Why is perfect F1 on this dataset weak evidence, and how would a stronger evaluation be designed?
- Which metrics must become durable or exported before production use?

## Truthful resume bullet drafts

- Built a FastAPI and PostgreSQL incident-intelligence backend with atomic multi-table ingestion,
  idempotent retries, cursor timelines, and database-enforced concurrency, with automated
  unit, API, and PostgreSQL integration tests.
- Designed a durable classification worker using row locking, `SKIP LOCKED`, recoverable leases,
  stale-worker fencing, exponential backoff, and replay-safe result persistence; packaged separate API, worker, and
  migration services in a non-root container workflow.
- Implemented evidence-cited deterministic classification and signed role-based human approvals;
  published a reproducible 12-case synthetic evaluation with explicit dataset and generalization
  limitations.

## Next work, intentionally deferred

A stronger next checkpoint would enlarge and independently label the evaluation set before adding
an optional budgeted GPT comparison. Production deployment, external connectors, enterprise SSO,
durable telemetry, alerting, and a browser interface are not represented as completed work.
