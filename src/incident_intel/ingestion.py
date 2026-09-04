import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol

from incident_intel.schemas import EventBundle


def canonical_bundle_json(bundle: EventBundle) -> str:
    return json.dumps(
        bundle.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def bundle_payload_hash(bundle: EventBundle) -> str:
    payload = canonical_bundle_json(bundle).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class IngestionRecord:
    idempotency_key: str
    correlation_id: str
    ticket_id: str
    log_count: int


class IdempotencyConflict(Exception):  # noqa: N818 - public domain name from the API contract
    """Raised when an idempotency key is reused for different canonical content."""


class CorrelationConflict(Exception):  # noqa: N818 - public domain name from the API contract
    """Raised when a correlation ID is already owned by another ingestion key."""


class StorageUnavailable(Exception):  # noqa: N818 - public domain name from the API contract
    """Raised when the configured durable store cannot complete an operation."""


class StorageIntegrityError(Exception):
    """Raised when validated input violates a durable storage constraint."""


class IngestionStore(Protocol):
    def ingest(
        self, idempotency_key: str, bundle: EventBundle
    ) -> tuple[IngestionRecord, bool]: ...


@dataclass
class InMemoryIngestionStore:
    records_by_key: dict[str, IngestionRecord] = field(default_factory=dict)
    payload_hash_by_key: dict[str, str] = field(default_factory=dict)
    key_by_correlation_id: dict[str, str] = field(default_factory=dict)

    def ingest(self, idempotency_key: str, bundle: EventBundle) -> tuple[IngestionRecord, bool]:
        payload_hash = bundle_payload_hash(bundle)
        existing_record = self.records_by_key.get(idempotency_key)
        if existing_record is not None:
            if self.payload_hash_by_key[idempotency_key] != payload_hash:
                raise IdempotencyConflict(idempotency_key)
            return existing_record, True

        existing_key = self.key_by_correlation_id.get(bundle.correlation_id)
        if existing_key is not None:
            raise CorrelationConflict(bundle.correlation_id)

        record = IngestionRecord(
            idempotency_key=idempotency_key,
            correlation_id=bundle.correlation_id,
            ticket_id=bundle.ticket.ticket_id,
            log_count=len(bundle.logs),
        )
        self.records_by_key[idempotency_key] = record
        self.payload_hash_by_key[idempotency_key] = payload_hash
        self.key_by_correlation_id[bundle.correlation_id] = idempotency_key
        return record, False
