import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import httpx
import pytest

from incident_intel.ingestion import IdempotencyConflict
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


def changed_request(request: WebhookDeliveryRequest, field: str) -> WebhookDeliveryRequest:
    changed = request.model_copy(deep=True)
    if field == "payload":
        changed.payload.ticket.subject = "Different synthetic incident"
    else:
        setattr(changed, field, "different-synthetic-value")
    return changed


@pytest.mark.parametrize("field", ["destination_name", "event_type", "payload"])
def test_conflicting_request_does_not_replace_original_delivery(field) -> None:
    store = InMemoryWebhookDeliveryStore()
    request = WebhookDeliveryRequest(
        destination_name="ticketing-demo", event_type="auth_failure.detected", payload=load_bundle()
    )
    first = record_webhook_delivery(
        store=store, idempotency_key="conflict-key-001", request=request, status_code=503
    )
    with pytest.raises(IdempotencyConflict):
        record_webhook_delivery(
            store=store, idempotency_key="conflict-key-001",
            request=changed_request(request, field), status_code=202,
        )
    replay = record_webhook_delivery(
        store=store, idempotency_key="conflict-key-001", request=request, status_code=202
    )
    assert replay.delivery_id == first.delivery_id
    assert replay.status == WebhookDeliveryStatus.RETRY_PENDING
    assert replay.next_retry_after_seconds == 30
    assert replay.attempt_count == 1
    assert replay.duplicate is True


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["destination_name", "event_type", "payload"])
async def test_preview_returns_409_for_changed_request_and_preserves_replay(app, field) -> None:
    request = WebhookDeliveryRequest(
        destination_name="ticketing-demo", event_type="auth_failure.detected", payload=load_bundle()
    )
    headers = {"Idempotency-Key": "api-conflict-key-001"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/webhooks/deliveries/preview", headers=headers, json=request.model_dump(mode="json")
        )
        conflict = await client.post(
            "/webhooks/deliveries/preview", headers=headers,
            json=changed_request(request, field).model_dump(mode="json"),
        )
        replay = await client.post(
            "/webhooks/deliveries/preview", headers=headers, json=request.model_dump(mode="json")
        )
    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json() == {
        "code": "idempotency_key_reused",
        "detail": "Idempotency key is already associated with a different webhook request.",
        "correlation_id": request.payload.correlation_id,
        "retryable": False,
    }
    assert replay.status_code == 200
    assert replay.json()["delivery_id"] == first.json()["delivery_id"]
    assert replay.json()["duplicate"] is True
    assert "different-synthetic-value" not in conflict.text


def test_equivalent_json_key_order_is_still_a_duplicate() -> None:
    store = InMemoryWebhookDeliveryStore()
    request = WebhookDeliveryRequest(
        destination_name="ticketing-demo", event_type="auth_failure.detected", payload=load_bundle()
    )
    original = request.model_dump(mode="json")
    reordered = dict(reversed(list(original.items())))
    reordered["payload"]["logs"][0]["attributes"] = dict(
        reversed(list(original["payload"]["logs"][0]["attributes"].items()))
    )
    first = record_webhook_delivery(
        store=store, idempotency_key="reordered-key-001", request=request, status_code=202
    )
    replay = record_webhook_delivery(
        store=store, idempotency_key="reordered-key-001",
        request=WebhookDeliveryRequest.model_validate(reordered), status_code=202,
    )
    assert replay.duplicate is True
    assert replay.delivery_id == first.delivery_id


def test_concurrent_conflicting_requests_have_one_winner() -> None:
    store = InMemoryWebhookDeliveryStore()
    request = WebhookDeliveryRequest(
        destination_name="ticketing-demo", event_type="auth_failure.detected", payload=load_bundle()
    )
    different = changed_request(request, "destination_name")
    start = Barrier(8)

    def submit(index):
        start.wait(timeout=5)
        try:
            return record_webhook_delivery(
                store=store, idempotency_key="concurrent-key-001",
                request=request if index % 2 else different, status_code=202,
            )
        except IdempotencyConflict:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(8)))
    accepted = [result for result in results if result is not None]
    assert len(accepted) == 4
    assert sum(not result.duplicate for result in accepted) == 1
    assert len({result.delivery_id for result in accepted}) == 1


def test_mutating_returned_record_does_not_change_saved_delivery() -> None:
    store = InMemoryWebhookDeliveryStore()
    request = WebhookDeliveryRequest(
        destination_name="ticketing-demo", event_type="auth_failure.detected", payload=load_bundle()
    )
    first = record_webhook_delivery(
        store=store, idempotency_key="immutable-key-001", request=request, status_code=202
    )
    first.destination_name = "mutated-return-value"
    replay = record_webhook_delivery(
        store=store, idempotency_key="immutable-key-001", request=request, status_code=202
    )
    assert replay.destination_name == "ticketing-demo"
