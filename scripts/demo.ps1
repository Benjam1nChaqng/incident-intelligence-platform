#Requires -Version 7.0
param(
    [string]$BaseUrl = "http://localhost:8000",
    [ValidatePattern('^[A-Za-z0-9]{1,32}$')]
    [string]$RunId = [Guid]::NewGuid().ToString("N")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$baseUri = $null
if (-not [Uri]::TryCreate($BaseUrl, [UriKind]::Absolute, [ref]$baseUri) -or
    $baseUri.Scheme -notin @("http", "https") -or
    $baseUri.Host -notin @("localhost", "127.0.0.1", "[::1]", "::1") -or
    $baseUri.UserInfo -or $baseUri.Query -or $baseUri.Fragment -or
    $baseUri.AbsolutePath -ne "/") {
    throw "BaseUrl must be a loopback HTTP(S) origin without credentials, a path, or a query."
}
$BaseUrl = $baseUri.GetLeftPart([UriPartial]::Authority)

if (-not $env:INCIDENT_INTEL_DATABASE_URL) {
    throw "Set INCIDENT_INTEL_DATABASE_URL before running the demo."
}
if ($env:INCIDENT_INTEL_TEST_DATABASE_URL -and
    $env:INCIDENT_INTEL_TEST_DATABASE_URL -cne $env:INCIDENT_INTEL_DATABASE_URL) {
    throw "Database URLs disagree. Clear INCIDENT_INTEL_TEST_DATABASE_URL before running the demo."
}
if (-not $env:INCIDENT_INTEL_TOKEN_SECRET -or $env:INCIDENT_INTEL_TOKEN_SECRET.Length -lt 32) {
    throw "Set INCIDENT_INTEL_TOKEN_SECRET to a local value of at least 32 characters."
}

function Assert-Demo {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Demo assertion failed: $Message" }
}

function New-DemoToken {
    param([string]$Role)
    $tokenOutput = @(& python -m incident_intel.token `
        --role $Role --operator-id "synthetic-demo-$Role" 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Local $Role token issuance failed." }
    $token = ($tokenOutput -join "").Trim()
    if ($token -notmatch '^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$') {
        throw "Local $Role token issuance returned an invalid token format."
    }
    return $token
}

function Invoke-DemoRequest {
    param([string]$Method, [string]$Path, [hashtable]$Headers, [int]$ExpectedStatus, [string]$Body)
    $request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::new($Method), "$BaseUrl$Path")
    $response = $null
    try {
        foreach ($name in $Headers.Keys) { $request.Headers.Add($name, [string]$Headers[$name]) }
        if ($Body) {
            $request.Content = [Net.Http.StringContent]::new($Body, [Text.Encoding]::UTF8, "application/json")
        }
        $response = $httpClient.SendAsync($request).GetAwaiter().GetResult()
        $status = [int]$response.StatusCode
        Assert-Demo ($status -eq $ExpectedStatus) "$Method $Path expected $ExpectedStatus, received $status."
        $json = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        return [pscustomobject]@{ StatusCode = $status; Data = $json }
    } finally {
        if ($response) { $response.Dispose() }
        $request.Dispose()
    }
}

# Capture native output and fail before any dependent step if a command fails.
$migrationOutput = @(& python -m alembic upgrade head 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Database migration failed; the demo did not continue." }
$viewerHeaders = @{ Authorization = "Bearer $(New-DemoToken viewer)" }
$operatorHeaders = @{ Authorization = "Bearer $(New-DemoToken operator)" }
Add-Type -AssemblyName System.Net.Http
$handler = [Net.Http.HttpClientHandler]::new()
$handler.AllowAutoRedirect = $false
$httpClient = [Net.Http.HttpClient]::new($handler)
$httpClient.Timeout = [TimeSpan]::FromSeconds(30)

try {

    $fixture = Get-Content -LiteralPath "$PSScriptRoot\..\tests\fixtures\auth_failure_bundle.json" -Raw |
        ConvertFrom-Json
    $fixture.correlation_id = "INC-DEMO-$RunId"
    $fixture.ticket.ticket_id = "TCK-DEMO-$RunId"
    for ($index = 0; $index -lt $fixture.logs.Count; $index++) {
        $fixture.logs[$index].event_id = "LOG-DEMO-$RunId-$($index + 1)"
    }
    $body = $fixture | ConvertTo-Json -Depth 20
    $idempotencyKey = "demo-$RunId"
    $ingestionHeaders = @{
        "Idempotency-Key" = $idempotencyKey
        Authorization = $operatorHeaders.Authorization
    }

    $accepted = Invoke-DemoRequest Post /events $ingestionHeaders 201 $body
    Assert-Demo ($accepted.Data.status -eq "accepted" -and -not $accepted.Data.duplicate) "new ingestion state"
    Assert-Demo ($accepted.Data.correlation_id -eq $fixture.correlation_id) "accepted correlation ID"
    $duplicate = Invoke-DemoRequest Post /events $ingestionHeaders 200 $body
    Assert-Demo ($duplicate.Data.status -eq "duplicate" -and $duplicate.Data.duplicate) "duplicate state"
    Assert-Demo ($duplicate.Data.ticket_id -eq $fixture.ticket.ticket_id) "duplicate ticket ID"

    $originalSubject = $fixture.ticket.subject
    $fixture.ticket.subject = "Changed synthetic subject for conflict proof"
    $changedBody = $fixture | ConvertTo-Json -Depth 20
    $conflict = Invoke-DemoRequest Post /events $ingestionHeaders 409 $changedBody
    Assert-Demo ($conflict.Data.code -eq "idempotency_key_reused") "conflict application code"
    $fixture.ticket.subject = $originalSubject

    $pagePath = "/incidents?limit=100"
    do {
        $page = (Invoke-DemoRequest Get $pagePath $viewerHeaders 200).Data
        $incident = @($page.items | Where-Object correlation_id -eq $fixture.correlation_id)
        if ($incident.Count -gt 0 -or -not $page.next_cursor) { break }
        $pagePath = "/incidents?limit=100&cursor=$([Uri]::EscapeDataString($page.next_cursor))"
    } while ($true)
    Assert-Demo ($incident.Count -eq 1) "exactly one newly ingested incident"
    $incidentId = $incident[0].incident_id
    $incidentDetail = (Invoke-DemoRequest Get "/incidents/$incidentId" $viewerHeaders 200).Data
    Assert-Demo ($incidentDetail.ticket.subject -eq $originalSubject) "conflict preserved original ticket"
    Assert-Demo ($incidentDetail.evidence.Count -eq $fixture.logs.Count) "persisted evidence count"
    for ($index = 0; $index -lt $fixture.logs.Count; $index++) {
        $actual = $incidentDetail.evidence[$index]
        $expected = $fixture.logs[$index]
        Assert-Demo ($actual.event_id -eq $expected.event_id) "ordered evidence ID $index"
        Assert-Demo ($actual.message -eq $expected.message) "persisted evidence message $index"
        Assert-Demo ($actual.service -eq $expected.service) "persisted evidence service $index"
        Assert-Demo ($actual.severity -eq $expected.severity) "persisted evidence severity $index"
        Assert-Demo ($actual.synthetic_user_id -eq $expected.synthetic_user_id) "synthetic evidence identity $index"
        Assert-Demo ([DateTimeOffset]$actual.observed_at -eq [DateTimeOffset]$expected.observed_at) "evidence timestamp $index"
        Assert-Demo (@($actual.attributes.PSObject.Properties).Count -eq
            @($expected.attributes.PSObject.Properties).Count) "evidence attribute count $index"
        foreach ($attribute in $expected.attributes.PSObject.Properties) {
            Assert-Demo ($actual.attributes.($attribute.Name) -eq $attribute.Value) "evidence attribute $index"
        }
    }

    $job = (Invoke-DemoRequest Post "/incidents/$incidentId/classifications" $operatorHeaders 202).Data
    $jobDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 250
        $job = (Invoke-DemoRequest Get "/jobs/$($job.job_id)" $viewerHeaders 200).Data
    } while ($job.state -notin @("completed", "failed") -and [DateTimeOffset]::UtcNow -lt $jobDeadline)
    Assert-Demo ($job.state -eq "completed") "classification job completed before timeout"
    Assert-Demo ($job.incident_id -eq $incidentId) "classification belongs to the incident"
    Assert-Demo (-not [string]::IsNullOrWhiteSpace($job.result_id)) "persisted classification result ID"
    Assert-Demo ($null -ne $job.completed_at) "classification completion timestamp"
    $classification = (Invoke-DemoRequest Get "/classifications/$($job.result_id)" $viewerHeaders 200).Data
    Assert-Demo ($classification.classification_id -eq $job.result_id -and
        $classification.incident_id -eq $incidentId) "persisted classification linkage"
    Assert-Demo ($classification.category -eq "authentication_failure") "classification category"
    Assert-Demo ($classification.provider -eq "deterministic_rules" -and
        $classification.model_version -eq "rules-v1") "classification provenance"
    Assert-Demo ($classification.cited_evidence_ids.Count -eq $fixture.logs.Count) "classification citation count"
    foreach ($eventId in $fixture.logs.event_id) {
        Assert-Demo ($eventId -in $classification.cited_evidence_ids) "classification cites persisted evidence"
    }

    $draft = (Invoke-DemoRequest Post "/incidents/$incidentId/drafts" $operatorHeaders 201).Data
    Assert-Demo ($draft.status -eq "pending_review" -and $null -eq $draft.decision) "draft starts undecided"
    Assert-Demo ($draft.created_by -eq "synthetic-demo-operator") "authenticated draft creator"
    $approved = (Invoke-DemoRequest Post "/drafts/$($draft.draft_id)/approve" $operatorHeaders 200 `
        '{"reason":"Synthetic evidence reviewed during the local demo."}').Data
    Assert-Demo ($approved.status -eq "approved" -and $approved.decision.decision -eq "approved") "approved decision"
    Assert-Demo ($approved.decision.operator_role -eq "operator") "decision uses operator role"
    Assert-Demo ($approved.decision.operator_id -eq "synthetic-demo-operator") "authenticated decision identity"
    $persistedDraft = (Invoke-DemoRequest Get "/drafts/$($draft.draft_id)" $viewerHeaders 200).Data
    Assert-Demo ($persistedDraft.status -eq "approved" -and
        $persistedDraft.decision.decision_id -eq $approved.decision.decision_id) "persisted approval decision"

    [pscustomobject]@{
        RunId = $RunId
        AcceptedStatus = [int]$accepted.StatusCode
        DuplicateStatus = [int]$duplicate.StatusCode
        ConflictStatus = $conflict.StatusCode
        ConflictCode = $conflict.Data.code
        EvidenceCount = $incidentDetail.evidence.Count
        JobState = $job.state
        ClassificationResultId = $job.result_id
        ClassificationCategory = $classification.category
        DraftInitialState = $draft.status
        DraftFinalState = $persistedDraft.status
        DecisionRole = $persistedDraft.decision.operator_role
    }
} finally {
    $httpClient.Dispose()
    $handler.Dispose()
    $viewerHeaders.Clear()
    $operatorHeaders.Clear()
    if (Get-Variable -Name ingestionHeaders -ErrorAction SilentlyContinue) { $ingestionHeaders.Clear() }
}
