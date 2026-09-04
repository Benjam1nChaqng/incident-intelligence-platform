from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

event_ingestions = Table(
    "event_ingestions",
    metadata,
    Column("idempotency_key", String(200), nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("correlation_id", String(80), nullable=False),
    Column("response_summary", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    CheckConstraint("char_length(payload_hash) = 64", name="ck_event_ingestions_hash_length"),
    PrimaryKeyConstraint("idempotency_key", name="pk_event_ingestions"),
)

incidents = Table(
    "incidents",
    metadata,
    Column("id", UUID(as_uuid=True), nullable=False),
    Column("correlation_id", String(80), nullable=False),
    Column("status", String(32), server_default=text("'open'"), nullable=False),
    Column("priority", String(16), nullable=False),
    Column("summary", String(160), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    PrimaryKeyConstraint("id", name="pk_incidents"),
    UniqueConstraint("correlation_id", name="uq_incidents_correlation_id"),
)

support_tickets = Table(
    "support_tickets",
    metadata,
    Column("ticket_id", String(64), nullable=False),
    Column(
        "incident_id",
        UUID(as_uuid=True),
        ForeignKey("incidents.id", name="fk_support_tickets_incident_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("subject", String(160), nullable=False),
    Column("description", Text, nullable=False),
    Column("priority", String(16), nullable=False),
    Column("source", String(32), nullable=False),
    Column("requester_role", String(80), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("tags", JSONB, nullable=False),
    PrimaryKeyConstraint("ticket_id", name="pk_support_tickets"),
)
Index("ix_support_tickets_incident_id", support_tickets.c.incident_id)

evidence_events = Table(
    "evidence_events",
    metadata,
    Column("event_id", String(64), nullable=False),
    Column(
        "incident_id",
        UUID(as_uuid=True),
        ForeignKey("incidents.id", name="fk_evidence_events_incident_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("service", String(80), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("message", String(1000), nullable=False),
    Column("synthetic_user_id", String(80), nullable=False),
    Column("attributes", JSONB, nullable=False),
    PrimaryKeyConstraint("event_id", name="pk_evidence_events"),
)
Index(
    "ix_evidence_events_incident_observed_at",
    evidence_events.c.incident_id,
    evidence_events.c.observed_at,
)

FOUNDATION_TABLES = (
    event_ingestions,
    incidents,
    support_tickets,
    evidence_events,
)
