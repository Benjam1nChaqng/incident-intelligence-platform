from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

FOUNDATION_TABLES = {
    "classifications",
    "event_ingestions",
    "incidents",
    "outbox_jobs",
    "response_drafts",
    "approval_decisions",
    "support_tickets",
    "evidence_events",
}


def alembic_config() -> Config:
    return Config(str(Path(__file__).parents[2] / "alembic.ini"))


def application_tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def index_names(engine: Engine, table_name: str) -> set[str]:
    return {index["name"] for index in inspect(engine).get_indexes(table_name)}


def test_foundation_migration_upgrades_downgrades_and_reupgrades(
    database_engine: Engine,
) -> None:
    config = alembic_config()

    command.upgrade(config, "head")

    assert application_tables(database_engine) == FOUNDATION_TABLES
    inspector = inspect(database_engine)
    assert inspector.get_pk_constraint("event_ingestions")["name"] == "pk_event_ingestions"
    assert inspector.get_pk_constraint("incidents")["name"] == "pk_incidents"
    assert inspector.get_pk_constraint("support_tickets")["name"] == "pk_support_tickets"
    assert inspector.get_pk_constraint("evidence_events")["name"] == "pk_evidence_events"
    assert inspector.get_foreign_keys("support_tickets")[0]["name"] == (
        "fk_support_tickets_incident_id"
    )
    assert inspector.get_foreign_keys("evidence_events")[0]["name"] == (
        "fk_evidence_events_incident_id"
    )
    assert inspector.get_foreign_keys("classifications")[0]["name"] == (
        "fk_classifications_incident_id"
    )
    assert inspector.get_foreign_keys("outbox_jobs")[0]["name"] == (
        "fk_outbox_jobs_incident_id"
    )
    assert inspector.get_foreign_keys("response_drafts")[0]["name"] == (
        "fk_response_drafts_incident_id"
    )
    assert inspector.get_foreign_keys("approval_decisions")[0]["name"] == (
        "fk_approval_decisions_draft_id"
    )
    assert "uq_incidents_correlation_id" in index_names(database_engine, "incidents")
    assert "ix_support_tickets_incident_id" in index_names(database_engine, "support_tickets")
    assert "ix_evidence_events_incident_observed_at" in index_names(
        database_engine, "evidence_events"
    )
    assert "ix_classifications_incident_created_at" in index_names(
        database_engine, "classifications"
    )
    assert "ix_outbox_jobs_claim" in index_names(database_engine, "outbox_jobs")
    assert "ix_response_drafts_incident_created_at" in index_names(
        database_engine, "response_drafts"
    )
    assert "uq_approval_decisions_draft_id" in index_names(
        database_engine, "approval_decisions"
    )

    command.downgrade(config, "base")

    assert application_tables(database_engine) == set()

    command.upgrade(config, "head")

    assert application_tables(database_engine) == FOUNDATION_TABLES
