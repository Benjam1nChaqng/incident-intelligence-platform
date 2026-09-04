from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Header, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine

from incident_intel import __version__
from incident_intel.approvals import (
    ApprovalRepository,
    Decision,
    DecisionRequest,
    DraftNotFound,
    DraftRecord,
    DraftStateConflict,
    build_response_draft,
)
from incident_intel.auth import (
    InvalidToken,
    OperatorClaims,
    OperatorRole,
    authorize,
    verify_token,
)
from incident_intel.auth_failures import AuthFailureEvidence, extract_auth_failure_evidence
from incident_intel.config import Settings
from incident_intel.incidents import (
    EmptyIncidentRepository,
    IncidentDetail,
    IncidentPage,
    IncidentRepository,
    InvalidCursor,
)
from incident_intel.ingestion import (
    CorrelationConflict,
    IdempotencyConflict,
    IngestionStore,
    InMemoryIngestionStore,
    StorageIntegrityError,
    StorageUnavailable,
)
from incident_intel.jobs import JobNotFound, JobRecord, JobRepository
from incident_intel.postgres import (
    PostgresIncidentRepository,
    PostgresIngestionStore,
    PostgresJobRepository,
    create_engine_from_url,
)
from incident_intel.postgres_approvals import PostgresApprovalRepository
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


def _storage_unavailable() -> JSONResponse:
    return _problem_response(
        503,
        ProblemDetail(
            code="storage_unavailable",
            detail="The configured incident store is temporarily unavailable.",
            correlation_id=None,
            retryable=True,
        ),
    )


def _approval_unavailable() -> JSONResponse:
    return _problem_response(
        503,
        ProblemDetail(
            code="approval_store_unavailable",
            detail="Durable approvals require the PostgreSQL storage backend.",
            correlation_id=None,
            retryable=False,
        ),
    )


def _draft_not_found() -> JSONResponse:
    return _problem_response(
        404,
        ProblemDetail(
            code="draft_not_found",
            detail="The requested response draft does not exist.",
            correlation_id=None,
            retryable=False,
        ),
    )


def _resolve_ingestion_store(
    settings: Settings | None,
    ingestion_store: IngestionStore | None,
    incident_repository: IncidentRepository | None,
    job_repository: JobRepository | None,
    approval_repository: ApprovalRepository | None,
) -> tuple[
    IngestionStore,
    IncidentRepository,
    JobRepository | None,
    ApprovalRepository | None,
    Engine | None,
]:
    if ingestion_store is not None:
        return (
            ingestion_store,
            incident_repository or EmptyIncidentRepository(),
            job_repository,
            approval_repository,
            None,
        )

    resolved_settings = settings if settings is not None else Settings.from_env()
    if resolved_settings.storage_backend == "memory":
        return (
            InMemoryIngestionStore(),
            incident_repository or EmptyIncidentRepository(),
            job_repository,
            approval_repository,
            None,
        )

    if resolved_settings.database_url is None:
        raise ValueError("INCIDENT_INTEL_DATABASE_URL is required for postgres storage")
    engine = create_engine_from_url(resolved_settings.database_url)
    return (
        PostgresIngestionStore(engine),
        incident_repository or PostgresIncidentRepository(engine),
        job_repository or PostgresJobRepository(engine),
        approval_repository or PostgresApprovalRepository(engine),
        engine,
    )


def create_app(
    *,
    settings: Settings | None = None,
    ingestion_store: IngestionStore | None = None,
    incident_repository: IncidentRepository | None = None,
    job_repository: JobRepository | None = None,
    approval_repository: ApprovalRepository | None = None,
) -> FastAPI:
    resolved_settings = settings
    if resolved_settings is None and ingestion_store is None:
        resolved_settings = Settings.from_env()
    (
        resolved_ingestion_store,
        resolved_incident_repository,
        resolved_job_repository,
        resolved_approval_repository,
        owned_engine,
    ) = (
        _resolve_ingestion_store(
            resolved_settings,
            ingestion_store,
            incident_repository,
            job_repository,
            approval_repository,
        )
    )
    webhook_delivery_store = InMemoryWebhookDeliveryStore()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owned_engine is not None:
                owned_engine.dispose()

    app = FastAPI(
        title="Incident Intelligence Platform",
        version=__version__,
        summary="Synthetic support incident investigation API.",
        lifespan=lifespan,
    )

    def authenticate(
        authorization: str | None,
        *,
        minimum_role: OperatorRole,
    ) -> OperatorClaims | JSONResponse:
        token_secret = resolved_settings.token_secret if resolved_settings else None
        if token_secret is None:
            return _problem_response(
                503,
                ProblemDetail(
                    code="authorization_unavailable",
                    detail="Operator authorization is not configured.",
                    correlation_id=None,
                    retryable=False,
                ),
            )
        if not authorization or not authorization.startswith("Bearer "):
            return _problem_response(
                401,
                ProblemDetail(
                    code="authentication_required",
                    detail="A valid short-lived operator token is required.",
                    correlation_id=None,
                    retryable=False,
                ),
            )
        try:
            claims = verify_token(authorization.removeprefix("Bearer "), secret=token_secret)
        except InvalidToken:
            return _problem_response(
                401,
                ProblemDetail(
                    code="invalid_token",
                    detail="The operator token is invalid or expired.",
                    correlation_id=None,
                    retryable=False,
                ),
            )
        if not authorize(claims, minimum_role=minimum_role):
            return _problem_response(
                403,
                ProblemDetail(
                    code="insufficient_role",
                    detail="The operator role is not permitted to perform this action.",
                    correlation_id=None,
                    retryable=False,
                ),
            )
        return claims

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
        except StorageIntegrityError:
            return _problem_response(
                409,
                ProblemDetail(
                    code="storage_identity_reused",
                    detail=(
                        "A ticket or evidence identifier is already assigned to another incident."
                    ),
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

    @app.get("/incidents", response_model=IncidentPage)
    def list_incidents(
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=512),
        status: str | None = Query(default=None, max_length=32),
        priority: str | None = Query(default=None, max_length=16),
    ) -> IncidentPage | JSONResponse:
        try:
            return resolved_incident_repository.list_incidents(
                limit=limit,
                cursor=cursor,
                status=status,
                priority=priority,
            )
        except InvalidCursor:
            return _problem_response(
                400,
                ProblemDetail(
                    code="invalid_cursor",
                    detail="The incident cursor is invalid or expired.",
                    correlation_id=None,
                    retryable=False,
                ),
            )
        except StorageUnavailable:
            return _problem_response(
                503,
                ProblemDetail(
                    code="storage_unavailable",
                    detail="The configured incident store is temporarily unavailable.",
                    correlation_id=None,
                    retryable=True,
                ),
            )

    @app.get("/incidents/{incident_id}", response_model=IncidentDetail)
    def get_incident(incident_id: UUID) -> IncidentDetail | JSONResponse:
        try:
            detail = resolved_incident_repository.get_incident(incident_id)
        except StorageUnavailable:
            return _problem_response(
                503,
                ProblemDetail(
                    code="storage_unavailable",
                    detail="The configured incident store is temporarily unavailable.",
                    correlation_id=None,
                    retryable=True,
                ),
            )
        if detail is None:
            return _problem_response(
                404,
                ProblemDetail(
                    code="incident_not_found",
                    detail="The requested incident does not exist.",
                    correlation_id=None,
                    retryable=False,
                ),
            )
        return detail

    @app.post(
        "/incidents/{incident_id}/classifications",
        response_model=JobRecord,
        status_code=202,
    )
    def create_classification_job(incident_id: UUID) -> JobRecord | JSONResponse:
        if resolved_job_repository is None:
            return _problem_response(
                503,
                ProblemDetail(
                    code="job_store_unavailable",
                    detail="Durable jobs require the PostgreSQL storage backend.",
                    correlation_id=None,
                    retryable=False,
                ),
            )
        try:
            if resolved_incident_repository.get_incident(incident_id) is None:
                return _problem_response(
                    404,
                    ProblemDetail(
                        code="incident_not_found",
                        detail="The requested incident does not exist.",
                        correlation_id=None,
                        retryable=False,
                    ),
                )
            return resolved_job_repository.create_classification_job(incident_id)
        except JobNotFound:
            return _problem_response(
                404,
                ProblemDetail(
                    code="incident_not_found",
                    detail="The requested incident does not exist.",
                    correlation_id=None,
                    retryable=False,
                ),
            )
        except StorageUnavailable:
            return _problem_response(
                503,
                ProblemDetail(
                    code="storage_unavailable",
                    detail="The configured incident store is temporarily unavailable.",
                    correlation_id=None,
                    retryable=True,
                ),
            )

    @app.get("/jobs/{job_id}", response_model=JobRecord)
    def get_job(job_id: UUID) -> JobRecord | JSONResponse:
        if resolved_job_repository is None:
            return _problem_response(
                503,
                ProblemDetail(
                    code="job_store_unavailable",
                    detail="Durable jobs require the PostgreSQL storage backend.",
                    correlation_id=None,
                    retryable=False,
                ),
            )
        try:
            job = resolved_job_repository.get_job(job_id)
        except StorageUnavailable:
            return _problem_response(
                503,
                ProblemDetail(
                    code="storage_unavailable",
                    detail="The configured incident store is temporarily unavailable.",
                    correlation_id=None,
                    retryable=True,
                ),
            )
        if job is None:
            return _problem_response(
                404,
                ProblemDetail(
                    code="job_not_found",
                    detail="The requested job does not exist.",
                    correlation_id=None,
                    retryable=False,
                ),
            )
        return job

    @app.post("/incidents/{incident_id}/drafts", response_model=DraftRecord, status_code=201)
    def create_response_draft(
        incident_id: UUID,
        authorization: str | None = Header(default=None),
    ) -> DraftRecord | JSONResponse:
        operator = authenticate(authorization, minimum_role="operator")
        if isinstance(operator, JSONResponse):
            return operator
        if resolved_approval_repository is None:
            return _approval_unavailable()
        try:
            incident = resolved_incident_repository.get_incident(incident_id)
            if incident is None:
                return _problem_response(
                    404,
                    ProblemDetail(
                        code="incident_not_found",
                        detail="The requested incident does not exist.",
                        correlation_id=None,
                        retryable=False,
                    ),
                )
            return resolved_approval_repository.create_draft(
                incident_id,
                content=build_response_draft(incident),
                created_by=operator.operator_id,
            )
        except StorageUnavailable:
            return _storage_unavailable()

    @app.get("/drafts/{draft_id}", response_model=DraftRecord)
    def get_response_draft(
        draft_id: UUID,
        authorization: str | None = Header(default=None),
    ) -> DraftRecord | JSONResponse:
        operator = authenticate(authorization, minimum_role="viewer")
        if isinstance(operator, JSONResponse):
            return operator
        if resolved_approval_repository is None:
            return _approval_unavailable()
        try:
            draft = resolved_approval_repository.get_draft(draft_id)
        except StorageUnavailable:
            return _storage_unavailable()
        if draft is None:
            return _draft_not_found()
        return draft

    def decide_response_draft(
        draft_id: UUID,
        *,
        decision: Decision,
        request: DecisionRequest,
        authorization: str | None,
    ) -> DraftRecord | JSONResponse:
        operator = authenticate(authorization, minimum_role="operator")
        if isinstance(operator, JSONResponse):
            return operator
        if resolved_approval_repository is None:
            return _approval_unavailable()
        try:
            return resolved_approval_repository.decide(
                draft_id,
                decision=decision,
                operator=operator,
                reason=request.reason,
            )
        except DraftNotFound:
            return _draft_not_found()
        except DraftStateConflict:
            return _problem_response(
                409,
                ProblemDetail(
                    code="draft_already_decided",
                    detail="The response draft already has a final operator decision.",
                    correlation_id=None,
                    retryable=False,
                ),
            )
        except StorageUnavailable:
            return _storage_unavailable()

    @app.post("/drafts/{draft_id}/approve", response_model=DraftRecord)
    def approve_response_draft(
        draft_id: UUID,
        request: DecisionRequest | None = None,
        authorization: str | None = Header(default=None),
    ) -> DraftRecord | JSONResponse:
        return decide_response_draft(
            draft_id,
            decision="approved",
            request=request or DecisionRequest(),
            authorization=authorization,
        )

    @app.post("/drafts/{draft_id}/reject", response_model=DraftRecord)
    def reject_response_draft(
        draft_id: UUID,
        request: DecisionRequest | None = None,
        authorization: str | None = Header(default=None),
    ) -> DraftRecord | JSONResponse:
        return decide_response_draft(
            draft_id,
            decision="rejected",
            request=request or DecisionRequest(),
            authorization=authorization,
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
