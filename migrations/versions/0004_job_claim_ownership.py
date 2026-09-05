"""Add durable job result linkage and per-attempt claim ownership."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_job_claim_ownership"
down_revision: str | None = "0003_operator_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox_jobs",
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_outbox_jobs_result_id",
        "outbox_jobs",
        "classifications",
        ["result_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_outbox_jobs_result_id",
        "outbox_jobs",
        type_="foreignkey",
    )
    op.drop_column("outbox_jobs", "claim_token")
