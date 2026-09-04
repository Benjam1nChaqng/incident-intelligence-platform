import copy
import json
from pathlib import Path

import httpx
import pytest

from incident_intel.ingestion import (
    CorrelationConflict,
    IdempotencyConflict,
    InMemoryIngestionStore,
    bundle_payload_hash,
    canonical_bundle_json,
)
from incident_intel.schemas import EventBundle

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "auth_failure_bundle.json"


def load_bundle() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_bundle_payload_hash_ignores_json_key_order() -> None:
    original = load_bundle()
    reordered = {
        "logs": copy.deepcopy(original["logs"]),
        "ticket": copy.deepcopy(original["ticket"]),
        "correlation_id": original["correlation_id"],
    }
    reordered["logs"][0]["attributes"] = {"result": "denied", "auth_method": "mfa_push"}

    first_bundle = EventBundle.model_validate(original)
    second_bundle = EventBundle.model_validate(reordered)

    assert canonical_bundle_json(first_bundle) == canonical_bundle_json(second_bundle)
    assert bundle_payload_hash(first_bundle) == bundle_payload_hash(second_bundle)
    assert bundle_payload_hash(first_bundle) == (
        "7c88819273b7fd74bdaa2f0a49568bd286fe7a1684152a45b1bb1960651297d6"
    )


def test_in_memory_store_returns_duplicate_for_same_key_and_payload() -> None:
    store = InMemoryIngestionStore()
    bundle = EventBundle.model_validate(load_bundle())

    first_record, first_duplicate = store.ingest("fixture-auth-failure-001", bundle)
    second_record, second_duplicate = store.ingest("fixture-auth-failure-001", bundle)

    assert first_duplicate is False
    assert second_duplicate is True
    assert second_record == first_record


def test_in_memory_store_rejects_same_key_with_changed_payload() -> None:
    store = InMemoryIngestionStore()
    bundle = EventBundle.model_validate(load_bundle())
    changed_bundle = bundle.model_copy(
        update={"ticket": bundle.ticket.model_copy(update={"subject": "Changed synthetic subject"})}
    )
    store.ingest("fixture-auth-failure-001", bundle)

    with pytest.raises(IdempotencyConflict):
        store.ingest("fixture-auth-failure-001", changed_bundle)


def test_in_memory_store_rejects_correlation_id_under_different_key() -> None:
    store = InMemoryIngestionStore()
    bundle = EventBundle.model_validate(load_bundle())
    store.ingest("fixture-auth-failure-001", bundle)

    with pytest.raises(CorrelationConflict):
        store.ingest("fixture-auth-failure-002", bundle)


@pytest.mark.anyio
async def test_ingest_event_bundle_records_new_idempotency_key(app) -> None:
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
async def test_ingest_event_bundle_deduplicates_repeated_idempotency_key(app) -> None:
    payload = load_bundle()
    payload["correlation_id"] = "INC-AUTH-DUPLICATE"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first_response = await client.post(
            "/events",
            headers={"Idempotency-Key": "fixture-auth-failure-duplicate"},
            json=payload,
        )
        second_response = await client.post(
            "/events",
            headers={"Idempotency-Key": "fixture-auth-failure-duplicate"},
            json=payload,
        )

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert second_response.json()["status"] == "duplicate"
    assert second_response.json()["duplicate"] is True
    assert second_response.json()["correlation_id"] == "INC-AUTH-DUPLICATE"


@pytest.mark.anyio
async def test_ingest_event_bundle_requires_idempotency_key(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/events", json=load_bundle())

    assert response.status_code == 422


@pytest.mark.anyio
async def test_ingest_event_bundle_rejects_key_larger_than_storage_column(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/events",
            headers={"Idempotency-Key": "x" * 201},
            json=load_bundle(),
        )

    assert response.status_code == 422
