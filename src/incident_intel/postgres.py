from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import Engine, create_engine, insert, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from incident_intel.db import event_ingestions, evidence_events, incidents, support_tickets
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
