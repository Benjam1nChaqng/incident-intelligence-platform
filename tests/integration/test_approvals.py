import asyncio
from pathlib import Path
from secrets import token_urlsafe
from threading import Event, Lock
from uuid import UUID

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event, func, select, text

from incident_intel.api import create_app
from incident_intel.auth import OperatorClaims, issue_token
from incident_intel.config import Settings
from incident_intel.db import approval_decisions
from incident_intel.postgres import PostgresIncidentRepository, PostgresIngestionStore
from incident_intel.postgres_approvals import PostgresApprovalRepository
from incident_intel.schemas import EventBundle

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "auth_failure_bundle.json"


@pytest.fixture(autouse=True)
def empty_tables(database_engine: Engine) -> None:
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")
    with database_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE incidents, event_ingestions CASCADE"))


def seed_incident(engine: Engine):
    bundle = EventBundle.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    PostgresIngestionStore(engine).ingest("fixture-approval-001", bundle)
    return PostgresIncidentRepository(engine).list_incidents().items[0].incident_id


def bearer(secret: str, *, role: str, operator_id: str) -> dict[str, str]:
    token = issue_token(
        OperatorClaims(operator_id=operator_id, role=role),  # type: ignore[arg-type]
        secret=secret,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_only_operator_can_create_and_decide_draft_once(
    database_url: str,
    database_engine: Engine,
) -> None:
    incident_id = seed_incident(database_engine)
    secret = token_urlsafe(32)
    app = create_app(
        settings=Settings(
            storage_backend="postgres",
            database_url=database_url,
            token_secret=secret,
        )
    )
    viewer = bearer(
        secret,
        role="viewer",
        operator_id="synthetic-viewer-1",
    )
    operator = bearer(
        secret,
        role="operator",
        operator_id="synthetic-operator-1",
    )
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthenticated = await client.post(f"/incidents/{incident_id}/drafts")
            forbidden_create = await client.post(
                f"/incidents/{incident_id}/drafts", headers=viewer
            )
            created = await client.post(
                f"/incidents/{incident_id}/drafts", headers=operator
            )
            draft_id = created.json()["draft_id"]
            viewed = await client.get(f"/drafts/{draft_id}", headers=viewer)
            forbidden_approval = await client.post(
                f"/drafts/{draft_id}/approve", headers=viewer
            )
            approved = await client.post(
                f"/drafts/{draft_id}/approve",
                headers=operator,
                json={"reason": "Synthetic evidence reviewed."},
            )
            second_decision = await client.post(
                f"/drafts/{draft_id}/reject",
                headers=operator,
                json={"reason": "Attempted second decision."},
            )

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["code"] == "authentication_required"
    assert forbidden_create.status_code == 403
    assert created.status_code == 201
    assert created.json()["status"] == "pending_review"
    assert viewed.status_code == 200
    assert viewed.json()["content"].startswith("Review incident INC-AUTH-0001")
    assert forbidden_approval.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["decision"]["operator_id"] == "synthetic-operator-1"
    assert second_decision.status_code == 409
    assert second_decision.json()["code"] == "draft_already_decided"
    with database_engine.connect() as connection:
        decision_count = connection.execute(
            select(func.count()).select_from(approval_decisions)
        ).scalar_one()
    assert decision_count == 1


@pytest.mark.anyio
async def test_admin_can_reject_pending_draft(
    database_url: str,
    database_engine: Engine,
) -> None:
    incident_id = seed_incident(database_engine)
    secret = token_urlsafe(32)
    settings = Settings(
        storage_backend="postgres",
        database_url=database_url,
        token_secret=secret,
    )
    app = create_app(settings=settings)
    operator = bearer(secret, role="operator", operator_id="synthetic-operator-1")
    admin = bearer(secret, role="admin", operator_id="synthetic-admin-1")
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                f"/incidents/{incident_id}/drafts", headers=operator
            )
            rejected = await client.post(
                f"/drafts/{created.json()['draft_id']}/reject",
                headers=admin,
                json={"reason": "Synthetic response needs revision."},
            )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["decision"]["operator_role"] == "admin"


@pytest.mark.anyio
async def test_concurrent_decision_requests_have_one_persisted_winner(
    database_url: str,
    database_engine: Engine,
) -> None:
    incident_id = seed_incident(database_engine)
    secret = token_urlsafe(32)
    app = create_app(
        settings=Settings(
            storage_backend="postgres", database_url=database_url, token_secret=secret
        ),
        approval_repository=PostgresApprovalRepository(database_engine),
    )
    operator = bearer(secret, role="operator", operator_id="synthetic-operator-1")
    first_locked = Event()
    second_attempting = Event()
    attempt_lock = Lock()
    attempts = 0

    def is_draft_lock(statement: str) -> bool:
        return "FROM response_drafts" in statement and "FOR UPDATE" in statement

    def before_execute(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal attempts
        if not is_draft_lock(statement):
            return
        with attempt_lock:
            attempts += 1
            attempt = attempts
        if attempt == 2:
            assert first_locked.wait(timeout=5), "First request never acquired the draft lock"
            second_attempting.set()

    def after_execute(_connection, _cursor, statement, _parameters, _context, _many):
        if is_draft_lock(statement) and not first_locked.is_set():
            first_locked.set()
            assert second_attempting.wait(timeout=5), "Second request never contested the lock"

    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(f"/incidents/{incident_id}/drafts", headers=operator)
            assert created.status_code == 201
            draft_id = created.json()["draft_id"]
            event.listen(database_engine, "before_cursor_execute", before_execute)
            event.listen(database_engine, "after_cursor_execute", after_execute)
            try:
                results = await asyncio.gather(
                    client.post(f"/drafts/{draft_id}/approve", headers=operator),
                    client.post(f"/drafts/{draft_id}/reject", headers=operator),
                )
            finally:
                event.remove(database_engine, "before_cursor_execute", before_execute)
                event.remove(database_engine, "after_cursor_execute", after_execute)

    assert first_locked.is_set() and second_attempting.is_set()
    assert sorted(result.status_code for result in results) == [200, 409]
    winner = next(result.json() for result in results if result.status_code == 200)
    loser = next(result.json() for result in results if result.status_code == 409)
    assert loser["code"] == "draft_already_decided"
    with database_engine.connect() as connection:
        decisions = connection.execute(
            select(approval_decisions).where(approval_decisions.c.draft_id == UUID(draft_id))
        ).mappings().all()
    assert len(decisions) == 1
    assert decisions[0]["decision"] == winner["status"]


def test_draft_and_decision_are_read_from_the_same_snapshot(database_engine: Engine) -> None:
    incident_id = seed_incident(database_engine)
    repository = PostgresApprovalRepository(database_engine)
    draft = repository.create_draft(
        incident_id, content="Synthetic review content", created_by="synthetic-operator-1"
    )
    operator = OperatorClaims(operator_id="synthetic-operator-1", role="operator")
    concurrent_decision_committed = False

    def after_select(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal concurrent_decision_committed
        if (
            concurrent_decision_committed
            or "FROM response_drafts" not in statement
            or "FOR UPDATE" in statement
        ):
            return
        concurrent_decision_committed = True
        repository.decide(draft.draft_id, decision="approved", operator=operator, reason=None)

    event.listen(database_engine, "after_cursor_execute", after_select)
    try:
        observed = repository.get_draft(draft.draft_id)
    finally:
        event.remove(database_engine, "after_cursor_execute", after_select)

    assert concurrent_decision_committed
    assert observed is not None
    assert observed.status == "pending_review"
    assert observed.decision is None
    committed = repository.get_draft(draft.draft_id)
    assert committed is not None
    assert committed.status == "approved"
    assert committed.decision is not None
