from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from incident_intel.schemas import EventBundle


class WebhookDeliveryStatus(StrEnum):
    DELIVERED = "delivered"
    RETRY_PENDING = "retry_pending"
    FAILED = "failed"


class WebhookDeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_name: str = Field(min_length=3, max_length=80)
    event_type: str = Field(min_length=6, max_length=120)
    payload: EventBundle


class WebhookDeliveryRecord(BaseModel):
    delivery_id: str
    idempotency_key: str
    destination_name: str
    event_type: str
    status: WebhookDeliveryStatus
    attempt_count: int
    duplicate: bool
    next_retry_after_seconds: int | None = None


@dataclass
class InMemoryWebhookDeliveryStore:
    records_by_key: dict[str, WebhookDeliveryRecord] = field(default_factory=dict)

    def get(self, idempotency_key: str) -> WebhookDeliveryRecord | None:
        return self.records_by_key.get(idempotency_key)

    def save(self, record: WebhookDeliveryRecord) -> None:
        self.records_by_key[record.idempotency_key] = record


def record_webhook_delivery(
    *,
    store: InMemoryWebhookDeliveryStore,
    idempotency_key: str,
    request: WebhookDeliveryRequest,
    status_code: int,
) -> WebhookDeliveryRecord:
    existing_record = store.get(idempotency_key)
    if existing_record is not None:
        return existing_record.model_copy(update={"duplicate": True})

    status = _status_from_code(status_code)
    record = WebhookDeliveryRecord(
        delivery_id=f"whd_{uuid4().hex}",
        idempotency_key=idempotency_key,
        destination_name=request.destination_name,
        event_type=request.event_type,
        status=status,
        attempt_count=1,
        duplicate=False,
        next_retry_after_seconds=30 if status is WebhookDeliveryStatus.RETRY_PENDING else None,
    )
    store.save(record)
    return record


def _status_from_code(status_code: int) -> WebhookDeliveryStatus:
    if 200 <= status_code <= 299:
        return WebhookDeliveryStatus.DELIVERED
    if status_code in {408, 425, 429} or 500 <= status_code <= 599:
        return WebhookDeliveryStatus.RETRY_PENDING
    return WebhookDeliveryStatus.FAILED
