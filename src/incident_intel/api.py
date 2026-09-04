from typing import Literal

from fastapi import FastAPI, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from incident_intel import __version__
from incident_intel.auth_failures import AuthFailureEvidence, extract_auth_failure_evidence
from incident_intel.config import Settings
from incident_intel.ingestion import (
    CorrelationConflict,
    IdempotencyConflict,
    IngestionStore,
    InMemoryIngestionStore,
    StorageUnavailable,
)
from incident_intel.postgres import PostgresIngestionStore, create_engine_from_url
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


class ProblemDetail(BaseModel):
    code: str
    detail: str
    correlation_id: str | None
    retryable: bool


def _problem_response(status_code: int, problem: ProblemDetail) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=problem.model_dump())


def _resolve_ingestion_store(
    settings: Settings | None,
    ingestion_store: IngestionStore | None,
) -> IngestionStore:
    if ingestion_store is not None:
        return ingestion_store

    resolved_settings = settings if settings is not None else Settings.from_env()
    if resolved_settings.storage_backend == "memory":
        return InMemoryIngestionStore()

    if resolved_settings.database_url is None:
        raise ValueError("INCIDENT_INTEL_DATABASE_URL is required for postgres storage")
    return PostgresIngestionStore(create_engine_from_url(resolved_settings.database_url))


def create_app(
    *,
    settings: Settings | None = None,
    ingestion_store: IngestionStore | None = None,
) -> FastAPI:
    resolved_ingestion_store = _resolve_ingestion_store(settings, ingestion_store)
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
        idempotency_key: str = Header(min_length=8, max_length=200),
    ) -> IngestionResponse | JSONResponse:
        try:
            record, duplicate = resolved_ingestion_store.ingest(idempotency_key, bundle)
        except IdempotencyConflict:
            return _problem_response(
                409,
                ProblemDetail(
                    code="idempotency_key_reused",
                    detail="Idempotency key is already associated with a different payload.",
                    correlation_id=bundle.correlation_id,
                    retryable=False,
                ),
            )
        except CorrelationConflict:
            return _problem_response(
                409,
                ProblemDetail(
                    code="correlation_id_reused",
                    detail="Correlation ID is already associated with a different ingestion.",
                    correlation_id=bundle.correlation_id,
                    retryable=False,
                ),
            )
        except StorageUnavailable:
            return _problem_response(
                503,
                ProblemDetail(
                    code="storage_unavailable",
                    detail="The configured incident store is temporarily unavailable.",
                    correlation_id=bundle.correlation_id,
                    retryable=True,
                ),
            )

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

    return app
