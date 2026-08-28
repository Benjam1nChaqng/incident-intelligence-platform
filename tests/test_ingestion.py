import json
from pathlib import Path

import httpx
import pytest

from incident_intel.api import app

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "auth_failure_bundle.json"


def load_bundle() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.anyio
async def test_ingest_event_bundle_records_new_idempotency_key() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/events",
            headers={"Idempotency-Key": "fixture-auth-failure-001"},
            json=load_bundle(),
        )

    assert response.status_code == 201
    assert response.json() == {
        "correlation_id": "INC-AUTH-0001",
        "idempotency_key": "fixture-auth-failure-001",
        "status": "accepted",
        "duplicate": False,
        "ticket_id": "TCK-1001",
        "log_count": 2,
    }


@pytest.mark.anyio
async def test_ingest_event_bundle_deduplicates_repeated_idempotency_key() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first_response = await client.post(
            "/events",
            headers={"Idempotency-Key": "fixture-auth-failure-duplicate"},
            json=load_bundle(),
        )
        second_response = await client.post(
            "/events",
            headers={"Idempotency-Key": "fixture-auth-failure-duplicate"},
            json=load_bundle(),
        )

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert second_response.json()["status"] == "duplicate"
    assert second_response.json()["duplicate"] is True
    assert second_response.json()["correlation_id"] == "INC-AUTH-0001"


@pytest.mark.anyio
async def test_ingest_event_bundle_requires_idempotency_key() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/events", json=load_bundle())

    assert response.status_code == 422
