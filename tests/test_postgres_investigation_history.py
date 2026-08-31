import json
from pathlib import Path

from incident_intel.ingestion import PostgresInvestigationHistoryStore
from incident_intel.schemas import EventBundle

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "auth_failure_bundle.json"


class FakeCursor:
    def __init__(self, rows: list[dict | None]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, dict | None]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: dict | None = None) -> None:
        self.executed.append((query, params))

    def fetchone(self) -> dict | None:
        return self.rows.pop(0)


class FakeConnection:
    def __init__(self, rows: list[dict | None]) -> None:
        self.cursor_instance = FakeCursor(rows)
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


def load_bundle() -> EventBundle:
    return EventBundle.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


def investigation_row() -> dict:
    return {
        "idempotency_key": "fixture-auth-failure-001",
        "correlation_id": "INC-AUTH-0001",
        "ticket_id": "TCK-1001",
        "log_count": 2,
    }


def test_postgres_history_store_inserts_new_investigation_record() -> None:
    connection = FakeConnection(rows=[investigation_row()])
    store = PostgresInvestigationHistoryStore(connection)

    record, duplicate = store.ingest("fixture-auth-failure-001", load_bundle())

    assert duplicate is False
    assert record.correlation_id == "INC-AUTH-0001"
    assert record.ticket_id == "TCK-1001"
    assert record.log_count == 2
    assert connection.commits == 1

    query, params = connection.cursor_instance.executed[0]
    assert "INSERT INTO investigation_history" in query
    assert "ON CONFLICT (idempotency_key) DO NOTHING" in query
    assert params is not None
    assert params["bundle"] == json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_postgres_history_store_returns_existing_record_for_duplicate_key() -> None:
    connection = FakeConnection(rows=[None, investigation_row()])
    store = PostgresInvestigationHistoryStore(connection)

    record, duplicate = store.ingest("fixture-auth-failure-001", load_bundle())

    assert duplicate is True
    assert record.idempotency_key == "fixture-auth-failure-001"
    assert record.correlation_id == "INC-AUTH-0001"
    assert connection.commits == 1

    executed_queries = [query for query, _params in connection.cursor_instance.executed]
    assert "INSERT INTO investigation_history" in executed_queries[0]
    assert "SELECT" in executed_queries[1]
    assert "WHERE idempotency_key = %(idempotency_key)s" in executed_queries[1]


def test_postgres_history_schema_declares_idempotency_boundary() -> None:
    schema = PostgresInvestigationHistoryStore.schema_sql()

    assert "CREATE TABLE IF NOT EXISTS investigation_history" in schema
    assert "idempotency_key text PRIMARY KEY" in schema
    assert "bundle jsonb NOT NULL" in schema
