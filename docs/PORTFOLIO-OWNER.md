# Incident Intelligence portfolio owner

Updated September 10, 2026. Owner: the Codex task `Portfolio owner - Incident Intelligence`.

## Mission and scope

Finish this existing project as an honest, reproducible local portfolio release. Coordinate all
daily portfolio work through this owner, close the finish checklist, then stop feature development.
The September 10 user instruction replaces open-ended daily feature building. Resume-builder is
only the source of the existing skill-gap handoff; it is not this owner's product or next project.

Repository: `C:\Users\bchang\Projects\incident-intelligence-platform`.
Daily automation ID: `daily-portfolio-build`. Retain 7:00 PM America/Los_Angeles daily.
Finish checklist: [September 10 plan](superpowers/plans/2026-09-10-portfolio-finish.md).
Architecture and prior acceptance: [case study](case-study.md).

Current closeout: the approved technical release `d4420f2` is published and its
[remote tests, standard Compose startup, and demo passed](verification-2026-09-10-publication.md).
Only Benji's personal interview rehearsal remains unassessed. Verify the documentation follow-up's
CI once, then stay quiet while that human item is unchanged. Do not reopen technical gates or start
features merely because the daily automation runs. His publication approval did not waive rehearsal.

## Single owner workflow

1. Read this file, the finish checklist, latest verification, and `git status --short --branch`.
   Record the absolute checkout, branch, HEAD, staged paths, and any other active portfolio task.
   Inspect changed files before choosing work. Never discard, stash, reset, or stage unrelated work.
2. Select the first unfinished, unblocked release gate. Do not manufacture daily iterations or
   implement new skills, integrations, UI, paid models, or a successor app to keep busy.
3. Delegate independent bounded work when useful. Give each worker exact files, acceptance tests,
   and permission boundaries. Only the owner integrates and commits; no concurrent writers to
   the same files or shared gap state. Worktrees must explicitly include the intended checkpoint.
4. Review the diff and run the relevant tests. Treat skipped database tests as unverified database
   behavior, historical runs as dated evidence, and old remote CI as proof only for its own SHA.
   Use existing local tools and only a new, explicitly disposable synthetic test database.
5. Record the evidence, changed paths, exact commands, result, and next gate in the finish checklist.
   Make a scoped local commit only after verification; never use `git add .` or `git add -A`.
6. Continue through unblocked gates in the same run while useful. Stop when all gates pass or only
   a concrete external/human prerequisite remains. Ask once with a prepared, reviewable result.
   On later runs stay quiet if that prerequisite is unchanged; do not append duplicate blockers.

## Close the existing handoff without weakening its claim gate

Read `C:\Users\bchang\Projects\resume-builder\artifacts\agent\gap-pipeline-active.json`
and `C:\Users\bchang\Projects\resume-builder\docs\gap-pipeline.md` without copying private
application data into this repository. Existing handoff: `gap-1485ed30cb95e41e`.

The completed synthetic lab has an [owner review](reviews/2026-09-10-offboarding-owner-review.md)
outside the CLI, which is the review location the pipeline specifies. Verify its four file hashes
before relying on it. Matching hashes plus passing tests close the technical portfolio review.
The source CLI cannot encode owner acceptance, so its `blocked` status is not by itself a reason
to repeat the lab or stop unrelated release checks. Preserve that state and every historical event.
Never hand-edit it or promote `resumeClaimEligible`, `productionExperienceVerified`, or vendor access.

If hashes change, review the changed bytes and supersede the review with a dated record. If the
handoff changes, inspect it but defer new lab expansion until this release is finished and Benji
selects further work. Do not clear the active handoff or choose the next skill automatically.

## Definition of done and stop condition

The local release is finished when the current code and synthetic lab are reviewed and committed,
all automated tests including PostgreSQL pass, lint and diff checks pass, deterministic evaluation
is reproducible, and demo/case-study instructions accurately state measured and unverified behavior.

Public portfolio closeout additionally requires user-authorized publication of the exact reviewed
revision, a successful remote CI run for that revision, and a standard Docker Compose startup
rehearsal or Benji's explicit acceptance of the documented Podman fallback limitation. Benji's
interview rehearsal is a human gate; the bot may prepare it but cannot claim he performed it.

Keep local completion, public closeout, and human rehearsal separate in status. Do not call the whole
project finished while a required gate remains. When all accepted gates are satisfied, inspect the
current automation and use `automation_update` to set `daily-portfolio-build` to `PAUSED`, preserving
its other fields. Issue one final evidence-backed handoff. Do not start another project until Benji
chooses it. If only authorization is missing, retain the checklist and avoid repetitive notifications.

## Authority

Authorized: reading, local planning, scoped reversible edits, tests, isolated synthetic test data,
local commits, independent review, and daily coordination. No new dependencies or host changes are
needed for this owner. Use native Codex scheduling, not a new server or always-on service.

Ask only at the final prepared step for push/publication, deployment, purchases, new installations,
real vendor or client operations, permissions, credentials, destructive changes, or a scope expansion.
No messages to employers, no applications, and no live resume edits belong to this portfolio owner.
The existing local daily schedule relies on the host being available; it is not cloud execution.
