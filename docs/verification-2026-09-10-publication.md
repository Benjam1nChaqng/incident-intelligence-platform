# Published release verification, September 10, 2026

## Approved publication

Benji approved pushing the 24 reviewed commits through
`d4420f21a3e6cb0942ef62944db5bc298dffe626` and running final GitHub checks.
The checkout was clean and remote main was still `946be4bbdb0ba6099f7ca5d3ca15b839c95ced39`.
An ancestry check passed; a non-force push published the exact approved descendant to
`Benjam1nChaqng/incident-intelligence-platform`. GitHub readback matched the approved SHA.

## Remote verification

[GitHub Actions run 34514582082](https://github.com/Benjam1nChaqng/incident-intelligence-platform/actions/runs/34514582082)
ran for `d4420f21a3e6cb0942ef62944db5bc298dffe626` and completed successfully at
`2026-09-10T18:29:50Z`. The Ubuntu job completed in 57 seconds.

- Empty-database migration: passed.
- Test suite with PostgreSQL: **138 passed, zero skips, 4.59 seconds**.
- Ruff: passed.
- Runtime Docker image build: passed.
- Standard `docker compose up --build --detach`: passed with database health and migration prerequisites.
- API readiness: passed before the demo ran.
- Existing deterministic PowerShell demo: passed every assertion.
- Fresh CI Compose project cleanup: passed; its disposable database volume and network were removed.

The demo's measured outputs were:

| Check | Result |
| --- | --- |
| First ingestion | 201 |
| Identical replay | 200 |
| Changed payload | 409, `idempotency_key_reused` |
| Persisted evidence | 2 records |
| Classification job | `completed` |
| Classification category | `authentication_failure` |
| Initial draft | `pending_review` |
| Final persisted draft | `approved` |
| Decision role | `operator` |

Exact verification commands after the approved push:

```powershell
gh api repos/Benjam1nChaqng/incident-intelligence-platform/commits/main --jq .sha
gh run watch 34514582082 --repo Benjam1nChaqng/incident-intelligence-platform --interval 15 --exit-status
gh run view 34514582082 --repo Benjam1nChaqng/incident-intelligence-platform --json headSha,status,conclusion,url,jobs
```

The job emitted a non-blocking annotation about the older action versions' Node runtime. Both
actions and the full job succeeded. No dependency refresh is needed to finish this release.

## Evidence boundaries and remaining work

This is a published, tested portfolio repository and container rehearsal, not a hosted production
service. The classifier and vendor-shaped fixture remain synthetic. The original local PostgreSQL
record and September 4 packaged outage/recovery evidence retain their own dates and environments.
No real tenant, customer data, paid model calls, or production deployment was used.

This record attributes remote evidence to the exact tested release SHA. A documentation-only
follow-up records these results; its CI must be checked separately before calling latest main green.

The technical finish gates are complete. Benji's personal interview rehearsal has not been performed
or assessed by the bot. The owner remains quiet while waiting for that one human closeout item, then
pauses daily builds after confirmation or explicit waiver. No successor project starts automatically.

## Interview handoff

Use the [90-second walkthrough and full question list](case-study.md#ninety-second-interview-walkthrough).
After the documented container setup, the demo command is:

```powershell
./scripts/demo.ps1
```

Start with this short explanation:

> I built a FastAPI and PostgreSQL backend that handles duplicate incident submissions, runs
> classification in a durable worker, and requires authenticated human approval for response drafts.
> Transactions keep incident records consistent. Worker leases and attempt tokens prevent stale
> workers from overwriting newer work. The classifier cites stored evidence, and the synthetic
> evaluation documents its limits.

Practice these three questions before marking rehearsal complete:

1. Why must the idempotency receipt and incident evidence share one transaction?
2. What fails if a worker marks a job complete before storing its result?
3. Why does perfect F1 on 12 designed synthetic cases not establish real-world accuracy?
