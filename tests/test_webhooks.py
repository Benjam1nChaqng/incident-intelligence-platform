import json
from pathlib import Path

import httpx
import pytest

from incident_intel.schemas import EventBundle
from incident_intel.webhooks import (
    InMemoryWebhookDeliveryStore,
    WebhookDeliveryRequest,
    WebhookDeliveryStatus,
    record_webhook_delivery,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "auth_failure_bundle.json"


def load_bundle() -> EventBundle:
    return EventBundle.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


def load_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_record_webhook_delivery_tracks_first_attempt() -> None:
    store = InMemoryWebhookDeliveryStore()
    request = WebhookDeliveryRequest(
        destination_name="ticketing-demo",
        event_type="auth_failure.detected",
        payload=load_bundle(),
    )

    delivery = record_webhook_delivery(
        store=store,
        idempotency_key="webhook-auth-failure-001",
        request=request,
        status_code=202,
    )

    assert delivery.status == WebhookDeliveryStatus.DELIVERED
    assert delivery.attempt_count == 1
    assert delivery.next_retry_after_seconds is None
    assert delivery.duplicate is False


def test_record_webhook_delivery_suppresses_duplicate_idempotency_key() -> None:
    store = InMemoryWebhookDeliveryStore()
    request = WebhookDeliveryRequest(
        destination_name="ticketing-demo",
        event_type="auth_failure.detected",
        payload=load_bundle(),
    )

    first_delivery = record_webhook_delivery(
        store=store,
        idempotency_key="webhook-auth-failure-duplicate",
        request=request,
        status_code=202,
    )
    second_delivery = record_webhook_delivery(
        store=store,
        idempotency_key="webhook-auth-failure-duplicate",
        request=request,
        status_code=202,
    )

    assert first_delivery.duplicate is False
    assert second_delivery.duplicate is True
    assert second_delivery.attempt_count == 1
    assert second_delivery.delivery_id == first_delivery.delivery_id


def test_record_webhook_delivery_marks_transient_failure_retryable() -> None:
    store = InMemoryWebhookDeliveryStore()
    request = WebhookDeliveryRequest(
        destination_name="ticketing-demo",
        event_type="auth_failure.detected",
        payload=load_bundle(),
    )

    delivery = record_webhook_delivery(
        store=store,
        idempotency_key="webhook-auth-failure-retry",
        request=request,
        status_code=503,
    )

    assert delivery.status == WebhookDeliveryStatus.RETRY_PENDING
    assert delivery.attempt_count == 1
    assert delivery.next_retry_after_seconds == 30


@pytest.mark.anyio
async def test_webhook_preview_endpoint_returns_delivery_state(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/webhooks/deliveries/preview",
            headers={"Idempotency-Key": "webhook-preview-auth-failure-001"},
            json={
                "destination_name": "ticketing-demo",
                "event_type": "auth_failure.detected",
                "payload": load_payload(),
            },
        )

    assert response.status_code == 201
    assert response.json()["status"] == "delivered"
    assert response.json()["attempt_count"] == 1
    assert response.json()["duplicate"] is False
