from dataclasses import dataclass, field

from incident_intel.schemas import EventBundle


@dataclass(frozen=True)
class IngestionRecord:
    idempotency_key: str
    correlation_id: str
    ticket_id: str
    log_count: int


@dataclass
class InMemoryIngestionStore:
    records_by_key: dict[str, IngestionRecord] = field(default_factory=dict)

    def ingest(self, idempotency_key: str, bundle: EventBundle) -> tuple[IngestionRecord, bool]:
        existing_record = self.records_by_key.get(idempotency_key)
        if existing_record is not None:
            return existing_record, True

        record = IngestionRecord(
            idempotency_key=idempotency_key,
            correlation_id=bundle.correlation_id,
            ticket_id=bundle.ticket.ticket_id,
            log_count=len(bundle.logs),
        )
        self.records_by_key[idempotency_key] = record
        return record, False
