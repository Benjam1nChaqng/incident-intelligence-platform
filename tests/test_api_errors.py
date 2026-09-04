import json
from pathlib import Path

import httpx
import pytest

from incident_intel.api import ProblemDetail, create_app
from incident_intel.ingestion import InMemoryIngestionStore, StorageUnavailable

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "auth_failure_bundle.json"


def load_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.anyio
async def test_idempotency_conflict_returns_stable_problem_detail() -> None:
    app = create_app(ingestion_store=InMemoryIngestionStore())
    payload = load_payload()
    changed_payload = load_payload()
    changed_payload["ticket"]["subject"] = "Changed synthetic subject"
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/events",
            headers={"Idempotency-Key": "fixture-auth-failure-conflict"},
            json=payload,
        )
        response = await client.post(
            "/events",
            headers={"Idempotency-Key": "fixture-auth-failure-conflict"},
            json=changed_payload,
        )

    assert response.status_code == 409
    assert response.json() == ProblemDetail(
        code="idempotency_key_reused",
        detail="Idempotency key is already associated with a different payload.",
        correlation_id="INC-AUTH-0001",
        retryable=False,
    ).model_dump()


@pytest.mark.anyio
async def test_correlation_conflict_returns_stable_problem_detail() -> None:
    app = create_app(ingestion_store=InMemoryIngestionStore())
    payload = load_payload()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/events",
            headers={"Idempotency-Key": "fixture-auth-failure-first"},
            json=payload,
        )
        response = await client.post(
            "/events",
            headers={"Idempotency-Key": "fixture-auth-failure-second"},
            json=payload,
        )

    assert response.status_code == 409
    assert response.json() == ProblemDetail(
        code="correlation_id_reused",
        detail="Correlation ID is already associated with a different ingestion.",
        correlation_id="INC-AUTH-0001",
        retryable=False,
    ).model_dump()


class UnavailableStore:
    def ingest(self, idempotency_key: str, bundle: object) -> None:
        raise StorageUnavailable


@pytest.mark.anyio
async def test_storage_unavailable_returns_retryable_problem_detail() -> None:
    app = create_app(ingestion_store=UnavailableStore())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/events",
            headers={"Idempotency-Key": "fixture-auth-failure-unavailable"},
            json=load_payload(),
        )

    assert response.status_code == 503
    assert response.json() == ProblemDetail(
        code="storage_unavailable",
        detail="The configured incident store is temporarily unavailable.",
        correlation_id="INC-AUTH-0001",
        retryable=True,
    ).model_dump()
