import json
import logging
import subprocess
import sys

import httpx
import pytest

from incident_intel.api import create_app
from incident_intel.ingestion import InMemoryIngestionStore
from incident_intel.observability import MetricsRegistry


def test_default_runtime_emits_json_request_logs_without_test_logging_setup() -> None:
    result = subprocess.run(
        [sys.executable, "-c", """
import asyncio
import httpx
from incident_intel.api import create_app
from incident_intel.config import Settings
async def main():
    app = create_app(settings=Settings(storage_backend='memory'))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url='http://testserver') as client:
        await client.get('/healthz')
asyncio.run(main())
"""], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    logs = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    assert len(logs) == 1
    assert logs[0]["path"] == "/healthz"
    assert logs[0]["status_code"] == 200


def test_metrics_registry_tracks_named_operations_and_latency() -> None:
    metrics = MetricsRegistry()

    metrics.increment("accepted")
    metrics.increment("retried", amount=2)
    metrics.observe_request(12.5)
    metrics.observe_request(7.5)

    snapshot = metrics.snapshot()
    assert snapshot.counters["accepted"] == 1
    assert snapshot.counters["retried"] == 2
    assert snapshot.request_latency.count == 2
    assert snapshot.request_latency.mean_ms == 10
    assert snapshot.request_latency.max_ms == 12.5


@pytest.mark.anyio
async def test_request_log_is_structured_and_does_not_include_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(ingestion_store=InMemoryIngestionStore())
    marker = "must-never-appear-in-request-log"
    payload = {
        "correlation_id": "INC-LOG-0001",
        "ticket": {
            "ticket_id": "TCK-LOG-0001",
            "subject": "Synthetic logging privacy verification",
            "description": f"Synthetic description containing {marker} for redaction proof.",
            "priority": "low",
            "source": "monitoring",
            "requester_role": "Synthetic Tester",
            "created_at": "2026-09-04T12:00:00Z",
            "tags": [],
        },
        "logs": [
            {
                "event_id": "LOG-PRIVACY-1",
                "observed_at": "2026-09-04T12:01:00Z",
                "service": "synthetic-service",
                "severity": "info",
                "message": "Synthetic evidence for request logging privacy.",
                "synthetic_user_id": "synthetic-user-privacy",
                "attributes": {},
            }
        ],
    }
    transport = httpx.ASGITransport(app=app)

    with caplog.at_level(logging.INFO, logger="incident_intel.requests"):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/events",
                headers={
                    "Idempotency-Key": "privacy-log-proof-001",
                    "X-Request-ID": "request-proof-001",
                    "X-Correlation-ID": "INC-LOG-0001",
                },
                json=payload,
            )
            metrics_response = await client.get("/metrics")

    request_logs = [json.loads(record.message) for record in caplog.records]
    assert response.status_code == 201
    assert all(marker not in record.message for record in caplog.records)
    assert request_logs[0]["request_id"] == "request-proof-001"
    assert request_logs[0]["correlation_id"] == "INC-LOG-0001"
    assert request_logs[0]["path"] == "/events"
    assert request_logs[0]["status_code"] == 201
    assert metrics_response.json()["counters"]["accepted"] == 1


@pytest.mark.anyio
async def test_readiness_is_separate_from_liveness() -> None:
    app = create_app(
        ingestion_store=InMemoryIngestionStore(),
        readiness_probe=lambda: False,
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        liveness = await client.get("/healthz")
        readiness = await client.get("/readyz")

    assert liveness.status_code == 200
    assert readiness.status_code == 503
    assert readiness.json()["status"] == "not_ready"
