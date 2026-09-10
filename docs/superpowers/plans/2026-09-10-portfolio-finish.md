# Incident Intelligence Portfolio Finish Plan

> For agentic workers: use `superpowers:subagent-driven-development` for independent implementation
> work or `superpowers:executing-plans` for sequential execution. Read the owner runbook first.

**Goal:** Finish and package the existing Incident Intelligence Platform, then end daily feature work.

**Architecture:** Keep the implemented FastAPI, PostgreSQL, durable worker, deterministic classifier,
and operator approval boundaries. A single persistent Codex owner coordinates the existing daily
schedule and reviews evidence. No custom bot server or new application subsystem is required.

**Tech stack:** Existing Python, pytest, Ruff, PostgreSQL 16, Alembic, containers, PowerShell, Codex.

**Spec:** `docs/superpowers/plans/2026-09-04-flagship-completion.md` and `docs/case-study.md`.
This is a release closeout plan, not a replacement architecture.

## Global constraints

- Synthetic data only; no real organization data, paid calls, external delivery, or resume promotion.
- Preserve existing work and the resume-builder handoff's immutable history and false claim flags.
- Keep one owner and one active release gate; delegate only independent file scopes.
- Push, publication, installation, deployment, and production mutation need explicit authorization.
- Current user direction takes priority over historical daily iteration counts and feature queues.

## Current baseline, September 10

The six implementation milestones already exist at `10338170146615deaa60ea9be20a33d3b896a792`.
The checkout began on `main`, 22 commits ahead of its remote-tracking ref, with only four untracked
offboarding files. GitHub readback confirmed public `main` at
`946be4bbdb0ba6099f7ca5d3ca15b839c95ced39`; its successful September 1 CI predates the local release.

Fresh pre-closeout verification: 24 offboarding tests passed; full suite 110 passed and 28 database
tests skipped because no disposable test database was configured. Ruff and `git diff --check`
passed. A fresh evaluation reproduced 12 synthetic cases with macro F1 1.0, citation validity 1.0,
abstention 0.25, and unsupported evidence 0.0. These are designed-fixture measurements only.

## Gate 1: Establish ownership and close the stale technical review

Files: `docs/PORTFOLIO-OWNER.md`, this plan,
`docs/reviews/2026-09-10-offboarding-owner-review.md`, existing four offboarding files.

- [x] Confirm Incident Intelligence is the user's target and inspect the existing daily schedule.
- [x] Independently review adapter, fixture, tests, and original evidence; compare SHA-256 receipts.
- [x] Accept the lab solely as an offline synthetic mapping through the existing EventBundle API.
- [x] Preserve source handoff state and claim flags; record technical acceptance outside its CLI.
- [x] Activate one persistent owner on the existing 7:00 PM Pacific daily schedule.
- [x] Commit the four reviewed offboarding files after complete verification: `75eb87f`.

Acceptance: no repeated waiting-for-owner loop for the reviewed bytes; no new lab is started.

## Gate 2: Verify the current release

Files: existing `tests/`, `data/evaluation_v1.json`, `docs/verification-2026-09-10-owner.md`.

- [x] Run `python -m pytest tests/test_offboarding.py -q` and review expected linkage and replay cases.
- [x] Run `python -m pytest -q` and explicitly record database skips.
- [x] Run `python -m ruff check .` and `git diff --check`.
- [x] Create a new isolated PostgreSQL 16 test container using existing tools; never reuse an old DB.
- [x] Set only that disposable database as the test target and run `python -m pytest -q` with no skips.
- [x] Reproduce the deterministic evaluation without overwriting the September 4 artifact.
- [x] Save sanitized commands/results, remove only this run's test resources, and record cleanup.

Fresh full result: **138 passed, zero skips, 23.86 seconds** against PostgreSQL 16.14.
The isolated empty-schema migration and cleanup passed. See
`docs/verification-2026-09-10-owner.md`; earlier skipped results above are superseded for this gate.

Acceptance: all 138 collected tests pass against an isolated database, or a specific failed check
is repaired and retested. A skipped suite cannot pass this gate. Any change to test count must be
explained by the reviewed diff. Do not install or reconfigure host software to force this gate.

## Gate 3: Package a reproducible local release

Files: `README.md`, `docs/case-study.md`, `docs/local-verification.md`, this plan.

- [x] Link current verification and synthetic lab review from the case study and README.
- [x] Reconcile current counts and release boundaries while retaining dated September 4 measurements.
- [x] Prepare publish scope: the reviewed local `main` descendant of public base `946be4b`, including
  the 22 existing release commits, offboarding commit `75eb87f`, and the owner/CI packaging commit.
  Resolve and present the exact final `git rev-parse HEAD` before asking for publication approval.
- [x] Review packaging diff and independent CI review; YAML and PowerShell parse validation passed.
- [x] Final staged privacy/whitespace review, scoped packaging commit, and clean-tree readback.
  The targeted credential-pattern scan covered 80 tracked paths with zero potential matches;
  this is a scoped scan, not a guarantee about every possible secret. The reviewed publish range
  contains 24 local commits including this owner/CI packaging commit.

Acceptance: a reviewer can reproduce the tests, understand the demo, and distinguish local evidence
from remote CI and actual vendor experience. No new feature is needed to pass this gate.

## Gate 4: Public closeout and standard startup

Files: existing `.github/workflows/ci.yml`, `compose.yaml`, `scripts/demo.ps1`, release records.

- [ ] Present the exact reviewed publish candidate and obtain authorization to push it to the
  already-public `Benjam1nChaqng/incident-intelligence-platform` repository.
- [ ] After authorization, recheck remote HEAD for concurrent changes and publish only the reviewed
  descendant without force. Verify GitHub's HEAD and successful CI for the exact pushed revision.
- [ ] On an available Docker Compose host, rehearse fresh startup, readiness, and `scripts/demo.ps1`;
  alternatively obtain Benji's explicit acceptance of the documented Podman fallback limitation.
- [x] Prepare a GitHub CI step for standard Compose startup, readiness, the existing demo, and
  cleanup of only that fresh CI project. YAML and embedded PowerShell parse checks passed locally.
  Execution remains staged until an authorized push runs it on GitHub's Ubuntu runner.

Acceptance: no old-CI, container-created, or image-built result is used as proof of an unrun demo.
This gate is currently pending publication authorization. The staged CI step supplies the standard
Docker environment after publication. WSL's `docker --version` returned Podman 5.3.1, so that local
command is not evidence of Docker Engine.

## Gate 5: Handoff and stop

Files: existing `docs/case-study.md` interview walkthrough and this checklist.

- [ ] Give Benji the existing 90-second walkthrough, demo command, and core tradeoff questions.
- [ ] Record his interview rehearsal only after he actually performs or explicitly waives it.
- [ ] Summarize verified release, any accepted limitations, published revision/CI, and deferred work.
- [ ] Pause `daily-portfolio-build` after all accepted finish gates pass; do not create the next app.

Deferred: broader Google/Okta/Slack/Jamf labs, live integrations, paid GPT comparisons, browser UI,
enterprise SSO, production deployment, durable telemetry, and more features. Revisit only for a new
explicit user goal after closeout. Release gates, not elapsed days or commit quotas, determine finish.

## Next owner action

Local closeout and packaging are complete. Publication authorization is pending; the exact final
revision is reported in the owner task. On approval recheck the remote, push without force, and inspect CI for
that exact revision including the new Compose demo step. Benji's interview rehearsal remains a
human gate. Do not repeat a blocked event or rerun unchanged tests on the next daily wakeup.
