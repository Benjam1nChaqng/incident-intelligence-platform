"""Add response drafts and append-only operator decisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_operator_approvals"
down_revision: str | None = "0002_intelligence_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "response_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending_review",
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=80), nullable=False),
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
        sa.CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected')",
            name="ck_response_drafts_status",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_response_drafts_incident_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_response_drafts"),
    )
    op.create_index(
        "ix_response_drafts_incident_created_at",
        "response_drafts",
        ["incident_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "approval_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("operator_id", sa.String(length=80), nullable=False),
        sa.Column("operator_role", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_approval_decisions_decision",
        ),
        sa.CheckConstraint(
            "operator_role IN ('operator', 'admin')",
            name="ck_approval_decisions_operator_role",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["response_drafts.id"],
            name="fk_approval_decisions_draft_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_approval_decisions"),
        sa.UniqueConstraint("draft_id", name="uq_approval_decisions_draft_id"),
    )


def downgrade() -> None:
    op.drop_table("approval_decisions")
    op.drop_index(
        "ix_response_drafts_incident_created_at",
        table_name="response_drafts",
    )
    op.drop_table("response_drafts")
