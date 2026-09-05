# Local container verification

This is the staged Podman fallback used to verify the packaged API, worker, migrations, and
PostgreSQL together. It does **not** establish that a single `docker compose up` command works:
Docker Compose itself has not been rehearsed on this host.

## Prerequisites and scope

- Run PowerShell 7.2+ from the repository root on Windows, with Python 3.12 available as `python`.
- The default WSL distribution must have Linux `python3`, rootful Podman, and working `sudo`.
  Do not enable or reconfigure these automatically on an existing machine.
- This sequence was exercised with Podman 5.3.1 and an isolated podman-compose 1.6.0 install.
  Network access is needed for package installation and container-image pulls.
- Ports `55431` and `58001` must be free. Only loopback ports are published. Use synthetic data.
- Use one PowerShell session throughout. Do not print environment variables, inspect full
  container configuration, enable verbose command logging, or record a transcript containing
  credentials. Random secrets are held in process environments, not written to `.env`.

The observed WSL host had no running systemd, so Podman healthcheck timers did not fire. Its
Podman/Compose combination also failed to start the nested one-shot migration dependency graph.
The fallback starts one stage at a time with `--no-deps`, **then explicitly verifies the same
prerequisites**. `k8s-file` logging avoids dependence on unavailable journald. It changes neither
the application's Compose file nor operating-system settings.

## Prepare an isolated verification run

The temporary provider install is not a global Python or operating-system installation. The
project name below isolates all containers, the network, and the deliberately disposable volume.

```powershell
$ErrorActionPreference = 'Stop'
if (-not (Test-Path ./compose.yaml)) { throw 'Run from the repository root.' }
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Local Python environment creation failed.' }
$originalPath = $env:Path
$env:Path = (Join-Path (Get-Location).Path '.venv\Scripts') + [IO.Path]::PathSeparator + $env:Path
$project = 'iipverify' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$repoLinux = (& wsl.exe -e wslpath -a (Get-Location).Path).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the checkout in WSL.' }
$tools = Join-Path ([IO.Path]::GetTempPath()) $project
New-Item -ItemType Directory -Path $tools | Out-Null
python -m pip install --target $tools podman-compose==1.6.0
if ($LASTEXITCODE -ne 0) { throw 'Isolated Compose provider install failed.' }
$toolsLinux = (& wsl.exe -e wslpath -a $tools).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve temporary tooling in WSL.' }
python -m pip install -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Local demo dependencies failed to install.' }

$env:POSTGRES_DB = 'incident_intel_verify'
$env:POSTGRES_USER = 'incident_intel_verify'
$env:POSTGRES_PASSWORD = [Convert]::ToHexString(
    [Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$env:POSTGRES_PORT = '55431'
$env:API_PORT = '58001'
$env:INCIDENT_INTEL_TOKEN_SECRET = [Convert]::ToHexString(
    [Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
$env:INCIDENT_INTEL_STORAGE_BACKEND = 'postgres'
$env:INCIDENT_INTEL_DATABASE_URL =
    "postgresql+psycopg://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@127.0.0.1:$($env:POSTGRES_PORT)/$($env:POSTGRES_DB)?connect_timeout=10"
Remove-Item Env:INCIDENT_INTEL_TEST_DATABASE_URL -ErrorAction SilentlyContinue
$baseUrl = "http://127.0.0.1:$($env:API_PORT)"

function Invoke-Podman {
    & wsl.exe --cd $repoLinux -e sudo podman @args
    if ($LASTEXITCODE -ne 0) { throw 'Podman command failed. Stop before the next stage.' }
}
function Invoke-Compose {
    $output = @(& wsl.exe --cd $repoLinux -e sudo env `
        "PYTHONPATH=$toolsLinux" `
        "POSTGRES_DB=$env:POSTGRES_DB" "POSTGRES_USER=$env:POSTGRES_USER" `
        "POSTGRES_PASSWORD=$env:POSTGRES_PASSWORD" "POSTGRES_PORT=$env:POSTGRES_PORT" `
        "API_PORT=$env:API_PORT" "INCIDENT_INTEL_TOKEN_SECRET=$env:INCIDENT_INTEL_TOKEN_SECRET" `
        python3 -m podman_compose --podman-run-args=--log-driver=k8s-file `
        -p $project -f compose.yaml @args 2>&1)
    $exitCode = $LASTEXITCODE
    foreach ($line in $output) {
        ([string]$line).Replace($env:POSTGRES_PASSWORD, '[REDACTED]').Replace(
            $env:INCIDENT_INTEL_TOKEN_SECRET, '[REDACTED]')
    }
    if ($exitCode -ne 0) { throw 'Compose command failed. Stop before the next stage.' }
}
function Wait-ContainerHealth([string]$Name) {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(60)
    do {
        & wsl.exe -e sudo podman healthcheck run $Name 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 2
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "Healthcheck did not pass within 60 seconds: $Name"
}

$existing = @(Invoke-Podman ps -a --filter "label=com.docker.compose.project=$project" --format '{{.Names}}')
if ($existing.Count -gt 0) { throw 'Project already exists; choose a fresh project name.' }
Invoke-Compose version
Invoke-Compose config | Out-Null
Invoke-Podman build --format docker -t incident-intelligence-platform:local .
foreach ($service in @('api', 'worker', 'migrate')) {
    Invoke-Podman tag localhost/incident-intelligence-platform:local "localhost/${project}_${service}:latest"
}
```

`INCIDENT_INTEL_TEST_DATABASE_URL` is deliberately removed from this session: Alembic's test
override must not point the demo at a different database. No tests are run against another stack.

## Gate startup and run the demo

Do not continue past a failed command or healthcheck. A created/running container alone is not
proof that its database schema or application is ready.

```powershell
Invoke-Compose up -d --no-build --no-deps postgres
Wait-ContainerHealth "${project}_postgres_1"

Invoke-Compose up -d --no-build --no-deps migrate
$migrationExit = [string](Invoke-Podman wait "${project}_migrate_1")
if ($migrationExit.Trim() -ne '0') { throw 'Migration did not finish successfully.' }

Invoke-Compose up -d --no-build --no-deps api worker
Wait-ContainerHealth "${project}_api_1"
$ready = Invoke-RestMethod "$baseUrl/readyz" -TimeoutSec 15
if ($ready.status -ne 'ready') { throw 'Host API is not ready.' }
Invoke-Podman exec "${project}_api_1" id -u
./scripts/demo.ps1 -BaseUrl $baseUrl
Invoke-Podman exec "${project}_postgres_1" psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB `
    -Atc 'SELECT version_num FROM alembic_version; SELECT count(*) FROM incidents; SELECT count(*) FROM classifications; SELECT count(*) FROM approval_decisions;'
```

Expected evidence: non-root UID `100`; migration revision `0004_job_claim_ownership`; one incident,
classification, and approval decision. The demo asserts `201` accepted, `200` duplicate, `409`
conflict, two stored evidence records, completed classification with matching citations, and a
draft moving from `pending_review` to a persisted operator `approved` decision.

## Verify database failure and recovery

Stop **only this run's disposable database**. The API must return `503` while it is down, then
recover to `200`/`ready`. The second demo proves the existing worker continues processing.

```powershell
Invoke-Podman stop --time 5 "${project}_postgres_1"
try {
    $down = Invoke-WebRequest "$baseUrl/readyz" -SkipHttpErrorCheck -TimeoutSec 15
    if ([int]$down.StatusCode -ne 503) { throw 'Expected readiness 503 while PostgreSQL is stopped.' }
} finally {
    Invoke-Podman start "${project}_postgres_1"
}
Wait-ContainerHealth "${project}_postgres_1"
Wait-ContainerHealth "${project}_api_1"
$ready = Invoke-RestMethod "$baseUrl/readyz" -TimeoutSec 15
if ($ready.status -ne 'ready') { throw 'API did not recover.' }
./scripts/demo.ps1 -BaseUrl $baseUrl
Invoke-Podman exec "${project}_postgres_1" psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB `
    -Atc 'SELECT count(*) FROM incidents; SELECT count(*) FROM classifications; SELECT count(*) FROM approval_decisions;'
Invoke-Podman logs --tail 40 "${project}_api_1"
Invoke-Podman logs --tail 20 "${project}_worker_1"
Invoke-Podman ps -a --filter "label=com.docker.compose.project=$project" --format '{{.Names}} {{.Status}}'
```

Expected final counts: `2`, `2`, `2`. API logs include structured request IDs, route templates,
status codes, and latency. A worker `worker_poll_failed` event may appear during the outage;
successful post-recovery processing is the decisive recovery check. Worker failure/retry counters
are emitted only when those counters change, not for successful jobs.

## Cleanup and evidence boundary

After collecting evidence, remove only the fresh project and its explicitly disposable synthetic
volume. This permanently removes **this verification run's** records; do not use `--volumes` on
an existing or valuable project. Other stacks are outside this procedure's scope.

```powershell
Invoke-Compose down --volumes
Invoke-Podman ps -a --filter "label=com.docker.compose.project=$project" --format '{{.Names}}'
Remove-Item Env:POSTGRES_PASSWORD, Env:INCIDENT_INTEL_TOKEN_SECRET, Env:INCIDENT_INTEL_DATABASE_URL
$env:Path = $originalPath
```

The final project-filtered container listing should be empty. Temporary provider tooling remains
in the operating system's temporary directory, and the project's dependencies remain in `.venv`;
neither installation changes global packages. Built images remain available for inspection. Record the
image ID, test results, date, and provider workaround in the case study. Do not label the staged
sequence a successful single-command Docker Compose rehearsal, a remote CI run, or a deployment.
