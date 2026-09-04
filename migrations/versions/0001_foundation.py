"""Create the durable incident ingestion foundation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_ingestions",
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=80), nullable=False),
        sa.Column("response_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(payload_hash) = 64",
            name="ck_event_ingestions_hash_length",
        ),
        sa.PrimaryKeyConstraint("idempotency_key", name="pk_event_ingestions"),
    )
    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'open'"), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_incidents"),
        sa.UniqueConstraint("correlation_id", name="uq_incidents_correlation_id"),
    )
    op.create_table(
        "support_tickets",
        sa.Column("ticket_id", sa.String(length=64), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("requester_role", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_support_tickets_incident_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ticket_id", name="pk_support_tickets"),
    )
    op.create_index(
        "ix_support_tickets_incident_id",
        "support_tickets",
        ["incident_id"],
        unique=False,
    )
    op.create_table(
        "evidence_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("service", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("synthetic_user_id", sa.String(length=80), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_evidence_events_incident_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_evidence_events"),
    )
    op.create_index(
        "ix_evidence_events_incident_observed_at",
        "evidence_events",
        ["incident_id", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_events_incident_observed_at", table_name="evidence_events")
    op.drop_table("evidence_events")
    op.drop_index("ix_support_tickets_incident_id", table_name="support_tickets")
    op.drop_table("support_tickets")
    op.drop_table("incidents")
    op.drop_table("event_ingestions")
