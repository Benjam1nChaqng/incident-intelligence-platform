import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

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


class Cursor(Protocol):
    def execute(self, query: str, params: dict[str, Any] | None = None) -> None: ...

    def fetchone(self) -> dict[str, Any] | None: ...


class Connection(Protocol):
    def cursor(self) -> Any: ...

    def commit(self) -> None: ...


@dataclass
class PostgresInvestigationHistoryStore:
    connection: Connection

    @staticmethod
    def schema_sql() -> str:
        return """
        CREATE TABLE IF NOT EXISTS investigation_history (
            idempotency_key text PRIMARY KEY,
            correlation_id text NOT NULL,
            ticket_id text NOT NULL,
            log_count integer NOT NULL,
            bundle jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """

    def ingest(self, idempotency_key: str, bundle: EventBundle) -> tuple[IngestionRecord, bool]:
        params = {
            "idempotency_key": idempotency_key,
            "correlation_id": bundle.correlation_id,
            "ticket_id": bundle.ticket.ticket_id,
            "log_count": len(bundle.logs),
            "bundle": bundle.model_dump(mode="json"),
        }
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO investigation_history (
                    idempotency_key,
                    correlation_id,
                    ticket_id,
                    log_count,
                    bundle
                )
                VALUES (
                    %(idempotency_key)s,
                    %(correlation_id)s,
                    %(ticket_id)s,
                    %(log_count)s,
                    %(bundle)s
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING idempotency_key, correlation_id, ticket_id, log_count
                """,
                params,
            )
            row = cursor.fetchone()
            duplicate = row is None

            if duplicate:
                cursor.execute(
                    """
                    SELECT idempotency_key, correlation_id, ticket_id, log_count
                    FROM investigation_history
                    WHERE idempotency_key = %(idempotency_key)s
                    """,
                    {"idempotency_key": idempotency_key},
                )
                row = cursor.fetchone()

        self.connection.commit()

        if row is None:
            raise LookupError("investigation history record was not written or found")

        return self._record_from_row(row), duplicate

    @staticmethod
    def _record_from_row(row: dict[str, Any]) -> IngestionRecord:
        return IngestionRecord(
            idempotency_key=str(row["idempotency_key"]),
            correlation_id=str(row["correlation_id"]),
            ticket_id=str(row["ticket_id"]),
            log_count=int(row["log_count"]),
        )
