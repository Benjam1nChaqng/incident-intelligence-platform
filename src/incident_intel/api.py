from typing import Literal

from fastapi import FastAPI, Header, Response
from pydantic import BaseModel

from incident_intel import __version__
from incident_intel.auth_failures import AuthFailureEvidence, extract_auth_failure_evidence
from incident_intel.ingestion import InMemoryIngestionStore
from incident_intel.runbooks import RunbookDraft, draft_runbook_response
from incident_intel.schemas import EventBundle
from incident_intel.webhooks import (
    InMemoryWebhookDeliveryStore,
    WebhookDeliveryRecord,
    WebhookDeliveryRequest,
    record_webhook_delivery,
)


class HealthResponse(BaseModel):
    service: str
    status: str
    version: str


class IngestionResponse(BaseModel):
    correlation_id: str
    idempotency_key: str
    status: Literal["accepted", "duplicate"]
    duplicate: bool
    ticket_id: str
    log_count: int


ingestion_store = InMemoryIngestionStore()
webhook_delivery_store = InMemoryWebhookDeliveryStore()

app = FastAPI(
    title="Incident Intelligence Platform",
    version=__version__,
    summary="Synthetic support incident investigation API.",
)


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(
        service="incident-intelligence-platform",
        status="ok",
        version=__version__,
    )


@app.post("/events", response_model=IngestionResponse, status_code=201)
def ingest_event_bundle(
    bundle: EventBundle,
    response: Response,
    idempotency_key: str = Header(min_length=8),
) -> IngestionResponse:
    record, duplicate = ingestion_store.ingest(idempotency_key, bundle)
    if duplicate:
        response.status_code = 200

    return IngestionResponse(
        correlation_id=record.correlation_id,
        idempotency_key=record.idempotency_key,
        status="duplicate" if duplicate else "accepted",
        duplicate=duplicate,
        ticket_id=record.ticket_id,
        log_count=record.log_count,
    )


@app.post("/investigations/auth-failure-preview", response_model=AuthFailureEvidence)
def preview_auth_failure_evidence(bundle: EventBundle) -> AuthFailureEvidence:
    return extract_auth_failure_evidence(bundle)


@app.post("/investigations/runbook-draft-preview", response_model=RunbookDraft)
def preview_runbook_draft(bundle: EventBundle) -> RunbookDraft:
    return draft_runbook_response(bundle)


@app.post("/webhooks/deliveries/preview", response_model=WebhookDeliveryRecord, status_code=201)
def preview_webhook_delivery(
    request: WebhookDeliveryRequest,
    response: Response,
    idempotency_key: str = Header(min_length=8),
) -> WebhookDeliveryRecord:
    delivery = record_webhook_delivery(
        store=webhook_delivery_store,
        idempotency_key=idempotency_key,
        request=request,
        status_code=202,
    )
    if delivery.duplicate:
        response.status_code = 200
    return delivery
