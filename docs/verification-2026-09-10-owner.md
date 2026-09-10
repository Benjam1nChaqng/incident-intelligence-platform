# Owner verification, September 10, 2026

Fresh local verification of the Incident Intelligence Platform at Git HEAD `10338170146615deaa60ea9be20a33d3b896a792`.
Started `2026-09-10T18:22:24.302489+00:00`; finished `2026-09-10T18:23:07.566290+00:00`. All repository fixture inputs are synthetic.

## Result

- Full suite with PostgreSQL enabled: **138 passed in 23.86s**, exit 0, zero skips.
- `python -m ruff check .`: `All checks passed!`, exit 0.
- `git diff --check`: exit 0, no output.
- Empty-database `python -m alembic upgrade head`: exit 0.
- Migration reversal and re-upgrade, transaction rollback/concurrency, worker ownership/retry,
  incident retrieval, role enforcement, and approval concurrency ran in the full integration suite.
- The 24 synthetic offboarding tests were included. This validates offline fixture adaptation,
  identity and endpoint linkage, missing-identity rejection, duplicate/conflicting event handling,
  stable timestamps and ordering, and existing-route replay.

## Isolation and runtime

- `Python 3.12.10` on Windows and `podman version 5.3.1` under WSL, using already installed tooling.
- Database reports PostgreSQL `16.14`; initial public schema contained zero tables.
- Cached image: `docker.io/library/postgres:16-alpine`, ID `de3a4eab8fdfa507ea92aac488b916b08089e515db49b055fe71dfa271ba3a28`.
- Fresh container name: `iip-owner-verify-16cc9feb6048434b`; only `127.0.0.1:45943` was published.
- Image pulling was disabled with `--pull never`. Database storage used a fresh tmpfs mount at
  `/var/lib/postgresql/data`; image volumes were ignored. No named or pre-existing storage was used.
- Random ephemeral database and signing credentials were generated in process memory. PostgreSQL
  settings were supplied through stdin; secrets and full connection URLs are omitted here.
- All inherited `INCIDENT_INTEL_*` settings were removed from the child process environment before
  explicit runtime/test URLs were set to this same fresh database. No inherited database was used.
- Only this new container was removed by its returned ID. `podman container exists` then returned 1,
  proving cleanup. Its tmpfs data was disposable. Existing containers and databases were untouched.

## Sanitized command sequence

From the repository root, one Python orchestration process ran these operations and checked every
exit code. Placeholders below describe ephemeral values; they are not literal runnable credentials.

```text
wsl.exe -e sudo -n podman container exists <fresh-name>  # expected 1 before creation
wsl.exe -e sudo -n podman run --pull never --detach --name <fresh-name> --log-driver k8s-file --publish 127.0.0.1::5432 --image-volume ignore --tmpfs /var/lib/postgresql/data:rw --env-file /dev/stdin docker.io/library/postgres:16-alpine
wsl.exe -e sudo -n podman port <returned-id> 5432/tcp
# Authenticated Windows psycopg readiness and PostgreSQL version/empty-schema checks
# Child environment: postgres backend, same fresh runtime/test URL, ephemeral token secret
python -m alembic upgrade head
python -m pytest -q
python -m ruff check .
git diff --check
git rev-parse HEAD
wsl.exe -e sudo -n podman rm --force --volumes <returned-id>
wsl.exe -e sudo -n podman container exists <returned-id>  # expected 1 after cleanup
```

## Evidence boundaries

This verifies the current local suite including PostgreSQL integration and the offboarding
simulation. It does not rerun the packaged API/worker demo or image build, prove standard
single-command Docker Compose startup, establish a remote CI run, publish anything, or assess
Benji's interview readiness. Earlier packaged-demo evidence remains dated September 4.
No real Google Workspace tenant was accessed. Vendor compatibility, production administration,
certification, and resume-claim eligibility remain unverified. No implementation files were changed
by this verification. The pre-existing untracked offboarding files were preserved.
