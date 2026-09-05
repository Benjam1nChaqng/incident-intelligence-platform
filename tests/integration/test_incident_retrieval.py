from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from incident_intel.api import create_app
from incident_intel.auth import OperatorClaims, issue_token
from incident_intel.config import Settings
from incident_intel.incidents import InvalidCursor
from incident_intel.postgres import PostgresIncidentRepository, PostgresIngestionStore
from incident_intel.schemas import EventBundle

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "auth_failure_bundle.json"


def viewer_headers(secret: str) -> dict[str, str]:
    token = issue_token(
        OperatorClaims(operator_id="synthetic-viewer-1", role="viewer"),
        secret=secret,
    )
    return {"Authorization": f"Bearer {token}"}


def bundle_for(index: int, *, priority: str = "high") -> EventBundle:
    bundle = EventBundle.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    return bundle.model_copy(
        update={
            "correlation_id": f"INC-AUTH-{index:04d}",
            "ticket": bundle.ticket.model_copy(
                update={"ticket_id": f"TCK-{index:04d}", "priority": priority}
            ),
            "logs": tuple(
                log.model_copy(update={"event_id": f"LOG-{index:04d}-{position}"})
                for position, log in enumerate(bundle.logs, start=1)
            ),
        }
    )


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


def test_list_incidents_uses_non_overlapping_cursor_pages(database_engine: Engine) -> None:
    store = PostgresIngestionStore(database_engine)
    repository = PostgresIncidentRepository(database_engine)
    for index in range(1, 4):
        store.ingest(f"fixture-list-{index:04d}", bundle_for(index))

    first_page = repository.list_incidents(limit=2)
    second_page = repository.list_incidents(limit=2, cursor=first_page.next_cursor)

    assert len(first_page.items) == 2
    assert first_page.next_cursor is not None
    assert len(second_page.items) == 1
    assert second_page.next_cursor is None
    first_ids = {item.incident_id for item in first_page.items}
    second_ids = {item.incident_id for item in second_page.items}
    assert first_ids.isdisjoint(second_ids)
    assert len(first_ids | second_ids) == 3


def test_list_incidents_filters_priority_and_rejects_invalid_cursor(
    database_engine: Engine,
) -> None:
    store = PostgresIngestionStore(database_engine)
    repository = PostgresIncidentRepository(database_engine)
    store.ingest("fixture-filter-high", bundle_for(10, priority="high"))
    store.ingest("fixture-filter-low", bundle_for(11, priority="low"))

    low_priority = repository.list_incidents(priority="low")

    assert [item.correlation_id for item in low_priority.items] == ["INC-AUTH-0011"]
    with pytest.raises(InvalidCursor):
        repository.list_incidents(cursor="not-a-valid-cursor")


def test_get_incident_returns_ticket_and_ordered_evidence(database_engine: Engine) -> None:
    store = PostgresIngestionStore(database_engine)
    repository = PostgresIncidentRepository(database_engine)
    store.ingest("fixture-detail-001", bundle_for(21))
    incident_id = repository.list_incidents().items[0].incident_id

    detail = repository.get_incident(incident_id)

    assert detail is not None
    assert detail.correlation_id == "INC-AUTH-0021"
    assert detail.ticket.ticket_id == "TCK-0021"
    assert detail.ticket.requester_role == "Finance Manager"
    assert [event.event_id for event in detail.evidence] == ["LOG-0021-1", "LOG-0021-2"]
    assert detail.evidence[0].observed_at < detail.evidence[1].observed_at


@pytest.mark.anyio
async def test_incident_api_lists_and_returns_detail(
    database_url: str,
    database_engine: Engine,
) -> None:
    PostgresIngestionStore(database_engine).ingest("fixture-api-detail", bundle_for(31))
    secret = token_urlsafe(32)
    app = create_app(
        settings=Settings(
            storage_backend="postgres",
            database_url=database_url,
            token_secret=secret,
        )
    )
    headers = viewer_headers(secret)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            list_response = await client.get(
                "/incidents", params={"limit": 1}, headers=headers
            )
            incident_id = list_response.json()["items"][0]["incident_id"]
            detail_response = await client.get(f"/incidents/{incident_id}", headers=headers)

    assert list_response.status_code == 200
    assert list_response.json()["next_cursor"] is None
    assert detail_response.status_code == 200
    assert detail_response.json()["ticket"]["ticket_id"] == "TCK-0031"
    assert len(detail_response.json()["evidence"]) == 2


@pytest.mark.anyio
async def test_incident_api_returns_stable_cursor_and_not_found_errors(
    database_url: str,
) -> None:
    secret = token_urlsafe(32)
    app = create_app(
        settings=Settings(
            storage_backend="postgres",
            database_url=database_url,
            token_secret=secret,
        )
    )
    headers = viewer_headers(secret)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            cursor_response = await client.get(
                "/incidents", params={"cursor": "invalid"}, headers=headers
            )
            missing_response = await client.get(f"/incidents/{uuid4()}", headers=headers)

    assert cursor_response.status_code == 400
    assert cursor_response.json()["code"] == "invalid_cursor"
    assert cursor_response.json()["retryable"] is False
    assert missing_response.status_code == 404
    assert missing_response.json()["code"] == "incident_not_found"
