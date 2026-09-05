from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Engine, and_, create_engine, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from incident_intel.classification import ClassificationRecord, ClassificationResult
from incident_intel.db import (
    classifications,
    event_ingestions,
    evidence_events,
    incidents,
    outbox_jobs,
    support_tickets,
)
from incident_intel.incidents import (
    EvidenceDetail,
    IncidentDetail,
    IncidentPage,
    IncidentSummary,
    TicketDetail,
    decode_incident_cursor,
    encode_incident_cursor,
)
from incident_intel.ingestion import (
    CorrelationConflict,
    IdempotencyConflict,
    IngestionRecord,
    StorageIntegrityError,
    StorageUnavailable,
    bundle_payload_hash,
)
from incident_intel.jobs import (
    InvalidJobState,
    JobNotFound,
    JobRecord,
    retry_delay,
    utc_now,
)
from incident_intel.schemas import EventBundle

JOB_CLAIM_LEASE = timedelta(minutes=5)


def create_engine_from_url(database_url: str) -> Engine:
    return create_engine(database_url, hide_parameters=True, pool_pre_ping=True)


@dataclass(frozen=True)
class PostgresIngestionStore:
    engine: Engine

    def ingest(self, idempotency_key: str, bundle: EventBundle) -> tuple[IngestionRecord, bool]:
        payload_hash = bundle_payload_hash(bundle)
        record = IngestionRecord(
            idempotency_key=idempotency_key,
            correlation_id=bundle.correlation_id,
            ticket_id=bundle.ticket.ticket_id,
            log_count=len(bundle.logs),
        )
        response_summary = {
            "correlation_id": record.correlation_id,
            "idempotency_key": record.idempotency_key,
            "status": "accepted",
            "duplicate": False,
            "ticket_id": record.ticket_id,
            "log_count": record.log_count,
        }
        incident_id = uuid4()

        try:
            with self.engine.begin() as connection:
                receipt_key = connection.execute(
                    postgres_insert(event_ingestions)
                    .values(
                        idempotency_key=idempotency_key,
                        payload_hash=payload_hash,
                        correlation_id=bundle.correlation_id,
                        response_summary=response_summary,
                    )
                    .on_conflict_do_nothing(index_elements=[event_ingestions.c.idempotency_key])
                    .returning(event_ingestions.c.idempotency_key)
                ).scalar_one_or_none()
                if receipt_key is None:
                    existing_receipt = connection.execute(
                        select(
                            event_ingestions.c.payload_hash,
                            event_ingestions.c.response_summary,
                        ).where(event_ingestions.c.idempotency_key == idempotency_key)
                    ).mappings().one_or_none()
                    if existing_receipt is None:
                        raise StorageUnavailable
                    if existing_receipt["payload_hash"] != payload_hash:
                        raise IdempotencyConflict(bundle.correlation_id)
                    return self._record_from_summary(existing_receipt["response_summary"]), True

                connection.execute(
                    insert(incidents).values(
                        id=incident_id,
                        correlation_id=bundle.correlation_id,
                        priority=bundle.ticket.priority,
                        summary=bundle.ticket.subject,
                    )
                )
                connection.execute(
                    insert(support_tickets).values(
                        ticket_id=bundle.ticket.ticket_id,
                        incident_id=incident_id,
                        subject=bundle.ticket.subject,
                        description=bundle.ticket.description,
                        priority=bundle.ticket.priority,
                        source=bundle.ticket.source,
                        requester_role=bundle.ticket.requester_role,
                        created_at=bundle.ticket.created_at,
                        tags=bundle.ticket.tags,
                    )
                )
                connection.execute(
                    insert(evidence_events),
                    [
                        {
                            "event_id": log.event_id,
                            "incident_id": incident_id,
                            "observed_at": log.observed_at,
                            "service": log.service,
                            "severity": log.severity,
                            "message": log.message,
                            "synthetic_user_id": log.synthetic_user_id,
                            "attributes": log.attributes,
                        }
                        for log in bundle.logs
                    ],
                )
        except IntegrityError as error:
            constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint_name == "uq_incidents_correlation_id":
                raise CorrelationConflict(bundle.correlation_id) from None
            raise StorageIntegrityError(
                "incident transaction violated a storage constraint"
            ) from None
        except SQLAlchemyError:
            raise StorageUnavailable from None

        return record, False

    @staticmethod
    def _record_from_summary(summary: dict[str, object]) -> IngestionRecord:
        return IngestionRecord(
            idempotency_key=str(summary["idempotency_key"]),
            correlation_id=str(summary["correlation_id"]),
            ticket_id=str(summary["ticket_id"]),
            log_count=int(summary["log_count"]),
        )


@dataclass(frozen=True)
class PostgresIncidentRepository:
    engine: Engine

    def list_incidents(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        status: str | None = None,
        priority: str | None = None,
    ) -> IncidentPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        conditions = []
        if status is not None:
            conditions.append(incidents.c.status == status)
        if priority is not None:
            conditions.append(incidents.c.priority == priority)
        if cursor is not None:
            position = decode_incident_cursor(cursor)
            conditions.append(
                or_(
                    incidents.c.created_at < position.created_at,
                    and_(
                        incidents.c.created_at == position.created_at,
                        incidents.c.id < position.incident_id,
                    ),
                )
            )

        statement = select(incidents)
        if conditions:
            statement = statement.where(and_(*conditions))
        statement = statement.order_by(
            incidents.c.created_at.desc(),
            incidents.c.id.desc(),
        ).limit(limit + 1)

        try:
            with self.engine.connect() as connection:
                rows = connection.execute(statement).mappings().all()
        except SQLAlchemyError:
            raise StorageUnavailable from None

        items = tuple(self._summary_from_row(row) for row in rows[:limit])
        next_cursor = encode_incident_cursor(items[-1]) if len(rows) > limit else None
        return IncidentPage(items=items, next_cursor=next_cursor)

    def get_incident(self, incident_id: UUID) -> IncidentDetail | None:
        try:
            with self.engine.connect() as connection:
                incident_row = connection.execute(
                    select(incidents).where(incidents.c.id == incident_id)
                ).mappings().one_or_none()
                if incident_row is None:
                    return None
                ticket_row = connection.execute(
                    select(support_tickets).where(support_tickets.c.incident_id == incident_id)
                ).mappings().one()
                evidence_rows = connection.execute(
                    select(evidence_events)
                    .where(evidence_events.c.incident_id == incident_id)
                    .order_by(evidence_events.c.observed_at, evidence_events.c.event_id)
                ).mappings().all()
        except SQLAlchemyError:
            raise StorageUnavailable from None

        summary = self._summary_from_row(incident_row)
        return IncidentDetail(
            **summary.model_dump(),
            ticket=TicketDetail(
                ticket_id=ticket_row["ticket_id"],
                subject=ticket_row["subject"],
                description=ticket_row["description"],
                priority=ticket_row["priority"],
                source=ticket_row["source"],
                requester_role=ticket_row["requester_role"],
                created_at=ticket_row["created_at"],
                tags=tuple(ticket_row["tags"]),
            ),
            evidence=tuple(
                EvidenceDetail(
                    event_id=row["event_id"],
                    observed_at=row["observed_at"],
                    service=row["service"],
                    severity=row["severity"],
                    message=row["message"],
                    synthetic_user_id=row["synthetic_user_id"],
                    attributes=row["attributes"],
                )
                for row in evidence_rows
            ),
        )

    @staticmethod
    def _summary_from_row(row) -> IncidentSummary:
        return IncidentSummary(
            incident_id=row["id"],
            correlation_id=row["correlation_id"],
            status=row["status"],
            priority=row["priority"],
            summary=row["summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True)
class PostgresJobRepository:
    engine: Engine

    def create_classification_job(
        self,
        incident_id: UUID,
        *,
        max_attempts: int = 3,
    ) -> JobRecord:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        job_id = uuid4()
        try:
            with self.engine.begin() as connection:
                exists = connection.execute(
                    select(incidents.c.id).where(incidents.c.id == incident_id)
                ).scalar_one_or_none()
                if exists is None:
                    raise JobNotFound
                row = connection.execute(
                    insert(outbox_jobs)
                    .values(
                        id=job_id,
                        incident_id=incident_id,
                        job_type="classify_incident",
                        payload={},
                        max_attempts=max_attempts,
                    )
                    .returning(outbox_jobs)
                ).mappings().one()
        except JobNotFound:
            raise
        except SQLAlchemyError:
            raise StorageUnavailable from None
        return self._job_from_row(row)

    def get_job(self, job_id: UUID) -> JobRecord | None:
        try:
            with self.engine.connect() as connection:
                row = connection.execute(
                    select(outbox_jobs).where(outbox_jobs.c.id == job_id)
                ).mappings().one_or_none()
        except SQLAlchemyError:
            raise StorageUnavailable from None
        return None if row is None else self._job_from_row(row)

    def get_classification(self, classification_id: UUID) -> ClassificationRecord | None:
        try:
            with self.engine.connect() as connection:
                row = connection.execute(
                    select(classifications).where(classifications.c.id == classification_id)
                ).mappings().one_or_none()
        except SQLAlchemyError:
            raise StorageUnavailable from None
        if row is None:
            return None
        return ClassificationRecord(classification_id=row["id"], **dict(row))

    def retry_job(self, job_id: UUID) -> JobRecord:
        try:
            with self.engine.begin() as connection:
                current = connection.execute(
                    select(outbox_jobs).where(outbox_jobs.c.id == job_id).with_for_update()
                ).mappings().one_or_none()
                if current is None:
                    raise JobNotFound
                if current["state"] != "failed":
                    raise InvalidJobState
                row = connection.execute(
                    update(outbox_jobs)
                    .where(outbox_jobs.c.id == job_id)
                    .values(
                        state="retry_pending",
                        max_attempts=current["attempt_count"] + 1,
                        next_attempt_at=utc_now(),
                        claimed_at=None,
                        claimed_by=None,
                        claim_token=None,
                        updated_at=utc_now(),
                    )
                    .returning(outbox_jobs)
                ).mappings().one()
        except SQLAlchemyError:
            raise StorageUnavailable from None
        return self._job_from_row(row)

    def claim_jobs(
        self,
        *,
        worker_id: str,
        limit: int = 10,
        now: datetime | None = None,
    ) -> tuple[JobRecord, ...]:
        if not worker_id or len(worker_id) > 80:
            raise ValueError("worker_id must contain 1 to 80 characters")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        claimed_at = now or utc_now()
        stale_before = claimed_at - JOB_CLAIM_LEASE
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    update(outbox_jobs)
                    .where(
                        outbox_jobs.c.state == "processing",
                        outbox_jobs.c.claimed_at <= stale_before,
                        outbox_jobs.c.attempt_count >= outbox_jobs.c.max_attempts,
                    )
                    .values(
                        state="failed",
                        claimed_at=None,
                        claimed_by=None,
                        claim_token=None,
                        last_error_class="WorkerLeaseExpired",
                        updated_at=claimed_at,
                    )
                )
                job_ids = connection.execute(
                    select(outbox_jobs.c.id)
                    .where(
                        or_(
                            and_(
                                outbox_jobs.c.state.in_(("pending", "retry_pending")),
                                outbox_jobs.c.next_attempt_at <= claimed_at,
                            ),
                            and_(
                                outbox_jobs.c.state == "processing",
                                outbox_jobs.c.claimed_at <= stale_before,
                                outbox_jobs.c.attempt_count < outbox_jobs.c.max_attempts,
                            ),
                        )
                    )
                    .order_by(outbox_jobs.c.next_attempt_at, outbox_jobs.c.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                ).scalars().all()
                if not job_ids:
                    return ()
                rows = []
                for job_id in job_ids:
                    rows.append(
                        connection.execute(
                            update(outbox_jobs)
                            .where(outbox_jobs.c.id == job_id)
                            .values(
                                state="processing",
                                attempt_count=outbox_jobs.c.attempt_count + 1,
                                claimed_at=claimed_at,
                                claimed_by=worker_id,
                                claim_token=uuid4(),
                                updated_at=claimed_at,
                            )
                            .returning(outbox_jobs)
                        ).mappings().one()
                    )
        except SQLAlchemyError:
            raise StorageUnavailable from None
        return tuple(self._job_from_row(row) for row in rows)

    def fail_job(
        self,
        job_id: UUID,
        error_class: str,
        *,
        claim_token: UUID,
        retryable: bool,
        now: datetime | None = None,
    ) -> JobRecord:
        failed_at = now or utc_now()
        safe_error = error_class[:80] or "UnknownError"
        try:
            with self.engine.begin() as connection:
                current = connection.execute(
                    select(outbox_jobs)
                    .where(outbox_jobs.c.id == job_id)
                    .with_for_update()
                ).mappings().one_or_none()
                if current is None:
                    raise JobNotFound
                if current["state"] != "processing" or current["claim_token"] != claim_token:
                    raise InvalidJobState
                should_retry = retryable and current["attempt_count"] < current["max_attempts"]
                next_attempt_at = (
                    failed_at + retry_delay(current["attempt_count"])
                    if should_retry
                    else current["next_attempt_at"]
                )
                row = connection.execute(
                    update(outbox_jobs)
                    .where(outbox_jobs.c.id == job_id)
                    .values(
                        state="retry_pending" if should_retry else "failed",
                        next_attempt_at=next_attempt_at,
                        claimed_at=None,
                        claimed_by=None,
                        claim_token=None,
                        last_error_class=safe_error,
                        updated_at=failed_at,
                    )
                    .returning(outbox_jobs)
                ).mappings().one()
        except (InvalidJobState, JobNotFound):
            raise
        except SQLAlchemyError:
            raise StorageUnavailable from None
        return self._job_from_row(row)

    def complete_classification(
        self,
        job_id: UUID,
        result: ClassificationResult,
        *,
        claim_token: UUID,
        now: datetime | None = None,
    ) -> JobRecord:
        completed_at = now or utc_now()
        result_id = uuid4()
        try:
            with self.engine.begin() as connection:
                current = connection.execute(
                    select(outbox_jobs)
                    .where(outbox_jobs.c.id == job_id)
                    .with_for_update()
                ).mappings().one_or_none()
                if current is None:
                    raise JobNotFound
                if current["state"] == "completed":
                    return self._job_from_row(current)
                if current["state"] != "processing" or current["claim_token"] != claim_token:
                    raise InvalidJobState
                connection.execute(
                    insert(classifications).values(
                        id=result_id,
                        incident_id=current["incident_id"],
                        provider=result.provider,
                        category=result.category,
                        confidence=result.confidence,
                        cited_evidence_ids=list(result.cited_evidence_ids),
                        reason_codes=list(result.reason_codes),
                        explanation=result.explanation,
                        model_version=result.model_version,
                        prompt_version=result.prompt_version,
                        latency_ms=result.latency_ms,
                    )
                )
                row = connection.execute(
                    update(outbox_jobs)
                    .where(outbox_jobs.c.id == job_id)
                    .values(
                        state="completed",
                        completed_at=completed_at,
                        result_id=result_id,
                        claimed_at=None,
                        claimed_by=None,
                        claim_token=None,
                        last_error_class=None,
                        updated_at=completed_at,
                    )
                    .returning(outbox_jobs)
                ).mappings().one()
        except (InvalidJobState, JobNotFound):
            raise
        except SQLAlchemyError:
            raise StorageUnavailable from None
        return self._job_from_row(row)

    @staticmethod
    def _job_from_row(row) -> JobRecord:
        return JobRecord(
            job_id=row["id"],
            incident_id=row["incident_id"],
            job_type=row["job_type"],
            state=row["state"],
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            next_attempt_at=row["next_attempt_at"],
            claimed_at=row["claimed_at"],
            claimed_by=row["claimed_by"],
            claim_token=row["claim_token"],
            completed_at=row["completed_at"],
            result_id=row["result_id"],
            last_error_class=row["last_error_class"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
