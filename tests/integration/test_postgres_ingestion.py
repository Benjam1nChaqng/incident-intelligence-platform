from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select, text

from incident_intel.api import create_app
from incident_intel.config import Settings
from incident_intel.db import event_ingestions, evidence_events, incidents, support_tickets
from incident_intel.ingestion import (
    CorrelationConflict,
    IdempotencyConflict,
    StorageIntegrityError,
    StorageUnavailable,
)
from incident_intel.postgres import PostgresIngestionStore, create_engine_from_url
from incident_intel.schemas import EventBundle

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "auth_failure_bundle.json"


def load_bundle() -> EventBundle:
    return EventBundle.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def empty_foundation_tables(database_engine: Engine) -> None:
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE evidence_events, support_tickets, incidents, "
                "event_ingestions CASCADE"
            )
        )


def table_count(engine: Engine, table) -> int:
    with engine.connect() as connection:
        return connection.execute(select(func.count()).select_from(table)).scalar_one()


def foundation_counts(engine: Engine) -> tuple[int, int, int, int]:
    return (
        table_count(engine, event_ingestions),
        table_count(engine, incidents),
        table_count(engine, support_tickets),
        table_count(engine, evidence_events),
    )


def test_ingest_persists_complete_incident_transaction(database_engine: Engine) -> None:
    store = PostgresIngestionStore(database_engine)

    record, duplicate = store.ingest("fixture-auth-failure-001", load_bundle())

    assert duplicate is False
    assert record.idempotency_key == "fixture-auth-failure-001"
    assert record.correlation_id == "INC-AUTH-0001"
    assert record.ticket_id == "TCK-1001"
    assert record.log_count == 2
    assert table_count(database_engine, event_ingestions) == 1
    assert table_count(database_engine, incidents) == 1
    assert table_count(database_engine, support_tickets) == 1
    assert table_count(database_engine, evidence_events) == 2

    with database_engine.connect() as connection:
        receipt = connection.execute(select(event_ingestions)).mappings().one()
        incident = connection.execute(select(incidents)).mappings().one()
        ticket = connection.execute(select(support_tickets)).mappings().one()
        evidence = connection.execute(
            select(evidence_events).order_by(evidence_events.c.event_id)
        ).mappings().all()

    assert receipt["payload_hash"] == (
        "7c88819273b7fd74bdaa2f0a49568bd286fe7a1684152a45b1bb1960651297d6"
    )
    assert receipt["response_summary"] == {
        "correlation_id": "INC-AUTH-0001",
        "idempotency_key": "fixture-auth-failure-001",
        "ticket_id": "TCK-1001",
        "log_count": 2,
    }
    assert incident["correlation_id"] == "INC-AUTH-0001"
    assert incident["priority"] == "high"
    assert incident["summary"] == "User cannot sign in after password reset"
    assert ticket["ticket_id"] == "TCK-1001"
    assert ticket["tags"] == ["authentication", "password-reset"]
    assert [row["event_id"] for row in evidence] == ["LOG-2001", "LOG-2002"]
    assert evidence[0]["attributes"] == {"auth_method": "mfa_push", "result": "denied"}


def test_ingest_returns_stored_summary_for_duplicate(database_engine: Engine) -> None:
    store = PostgresIngestionStore(database_engine)
    bundle = load_bundle()

    first_record, first_duplicate = store.ingest("fixture-auth-failure-duplicate", bundle)
    second_record, second_duplicate = store.ingest("fixture-auth-failure-duplicate", bundle)

    assert first_duplicate is False
    assert second_duplicate is True
    assert second_record == first_record
    assert foundation_counts(database_engine) == (1, 1, 1, 2)


def test_ingest_rejects_same_key_with_changed_payload(database_engine: Engine) -> None:
    store = PostgresIngestionStore(database_engine)
    bundle = load_bundle()
    changed_bundle = bundle.model_copy(
        update={"ticket": bundle.ticket.model_copy(update={"subject": "Changed synthetic subject"})}
    )
    store.ingest("fixture-auth-failure-conflict", bundle)

    with pytest.raises(IdempotencyConflict):
        store.ingest("fixture-auth-failure-conflict", changed_bundle)

    assert foundation_counts(database_engine) == (1, 1, 1, 2)


def test_ingest_rejects_same_correlation_under_different_key(database_engine: Engine) -> None:
    store = PostgresIngestionStore(database_engine)
    bundle = load_bundle()
    store.ingest("fixture-auth-failure-first", bundle)

    with pytest.raises(CorrelationConflict):
        store.ingest("fixture-auth-failure-second", bundle)

    assert foundation_counts(database_engine) == (1, 1, 1, 2)


def test_ingest_rolls_back_every_table_on_evidence_integrity_failure(
    database_engine: Engine,
) -> None:
    store = PostgresIngestionStore(database_engine)
    bundle = load_bundle()
    duplicate_evidence_bundle = bundle.model_copy(update={"logs": (bundle.logs[0], bundle.logs[0])})

    with pytest.raises(
        StorageIntegrityError,
        match="incident transaction violated a storage constraint",
    ):
        store.ingest("fixture-auth-failure-rollback", duplicate_evidence_bundle)

    assert foundation_counts(database_engine) == (0, 0, 0, 0)


def test_concurrent_same_key_ingestion_has_one_winner(database_engine: Engine) -> None:
    store = PostgresIngestionStore(database_engine)
    bundle = load_bundle()
    barrier = Barrier(2)

    def ingest_after_barrier():
        barrier.wait(timeout=5)
        return store.ingest("fixture-auth-failure-concurrent", bundle)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ingest_after_barrier) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]

    records = [record for record, _duplicate in results]
    duplicates = [duplicate for _record, duplicate in results]
    assert sorted(duplicates) == [False, True]
    assert records[0] == records[1]
    assert records[0].correlation_id == "INC-AUTH-0001"
    assert foundation_counts(database_engine) == (1, 1, 1, 2)


@pytest.mark.anyio
async def test_create_app_selects_postgres_store(
    database_url: str,
    database_engine: Engine,
) -> None:
    app = create_app(
        settings=Settings(storage_backend="postgres", database_url=database_url)
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/events",
            headers={"Idempotency-Key": "fixture-auth-failure-api"},
            json=load_bundle().model_dump(mode="json"),
        )

    assert response.status_code == 201
    assert response.json()["status"] == "accepted"
    assert foundation_counts(database_engine) == (1, 1, 1, 2)


def test_unreachable_database_raises_safe_storage_unavailable() -> None:
    engine = create_engine_from_url(
        "postgresql+psycopg://demo:secret-marker@127.0.0.1:1/demo?connect_timeout=1"
    )
    store = PostgresIngestionStore(engine)

    with pytest.raises(StorageUnavailable) as error:
        store.ingest("fixture-auth-failure-unavailable", load_bundle())

    assert "secret-marker" not in str(error.value)
    assert "postgresql" not in str(error.value)
    engine.dispose()


def test_engine_hides_statement_parameters() -> None:
    engine = create_engine_from_url(
        "postgresql+psycopg://demo:secret-marker@127.0.0.1:1/demo?connect_timeout=1"
    )

    assert engine.hide_parameters is True

    engine.dispose()
