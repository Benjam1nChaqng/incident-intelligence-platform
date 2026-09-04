from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import Engine, and_, create_engine, insert, or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from incident_intel.db import event_ingestions, evidence_events, incidents, support_tickets
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
from incident_intel.schemas import EventBundle


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
