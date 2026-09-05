from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
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

classifications = Table(
    "classifications",
    metadata,
    Column("id", UUID(as_uuid=True), nullable=False),
    Column(
        "incident_id",
        UUID(as_uuid=True),
        ForeignKey("incidents.id", name="fk_classifications_incident_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("provider", String(80), nullable=False),
    Column("category", String(80), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("cited_evidence_ids", JSONB, nullable=False),
    Column("reason_codes", JSONB, nullable=False),
    Column("explanation", Text, nullable=False),
    Column("model_version", String(80), nullable=False),
    Column("prompt_version", String(80), nullable=False),
    Column("latency_ms", Float, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    PrimaryKeyConstraint("id", name="pk_classifications"),
)
Index(
    "ix_classifications_incident_created_at",
    classifications.c.incident_id,
    classifications.c.created_at,
)

outbox_jobs = Table(
    "outbox_jobs",
    metadata,
    Column("id", UUID(as_uuid=True), nullable=False),
    Column(
        "incident_id",
        UUID(as_uuid=True),
        ForeignKey("incidents.id", name="fk_outbox_jobs_incident_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("job_type", String(80), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("state", String(32), server_default=text("'pending'"), nullable=False),
    Column("attempt_count", Integer, server_default=text("0"), nullable=False),
    Column("max_attempts", Integer, server_default=text("3"), nullable=False),
    Column(
        "next_attempt_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    Column("claimed_at", DateTime(timezone=True), nullable=True),
    Column("claimed_by", String(80), nullable=True),
    Column("claim_token", UUID(as_uuid=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column(
        "result_id",
        UUID(as_uuid=True),
        ForeignKey(
            "classifications.id",
            name="fk_outbox_jobs_result_id",
            ondelete="SET NULL",
        ),
        nullable=True,
    ),
    Column("last_error_class", String(80), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    CheckConstraint(
        "state IN ('pending', 'processing', 'retry_pending', 'completed', 'failed')",
        name="ck_outbox_jobs_state",
    ),
    CheckConstraint("attempt_count >= 0", name="ck_outbox_jobs_attempt_count"),
    CheckConstraint("max_attempts > 0", name="ck_outbox_jobs_max_attempts"),
    PrimaryKeyConstraint("id", name="pk_outbox_jobs"),
)
Index(
    "ix_outbox_jobs_claim",
    outbox_jobs.c.state,
    outbox_jobs.c.next_attempt_at,
    outbox_jobs.c.created_at,
)

response_drafts = Table(
    "response_drafts",
    metadata,
    Column("id", UUID(as_uuid=True), nullable=False),
    Column(
        "incident_id",
        UUID(as_uuid=True),
        ForeignKey("incidents.id", name="fk_response_drafts_incident_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("content", Text, nullable=False),
    Column("status", String(32), server_default=text("'pending_review'"), nullable=False),
    Column("created_by", String(80), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    CheckConstraint(
        "status IN ('pending_review', 'approved', 'rejected')",
        name="ck_response_drafts_status",
    ),
    PrimaryKeyConstraint("id", name="pk_response_drafts"),
)
Index(
    "ix_response_drafts_incident_created_at",
    response_drafts.c.incident_id,
    response_drafts.c.created_at,
)

approval_decisions = Table(
    "approval_decisions",
    metadata,
    Column("id", UUID(as_uuid=True), nullable=False),
    Column(
        "draft_id",
        UUID(as_uuid=True),
        ForeignKey(
            "response_drafts.id",
            name="fk_approval_decisions_draft_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    ),
    Column("decision", String(32), nullable=False),
    Column("operator_id", String(80), nullable=False),
    Column("operator_role", String(32), nullable=False),
    Column("reason", String(500), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
    CheckConstraint(
        "decision IN ('approved', 'rejected')",
        name="ck_approval_decisions_decision",
    ),
    CheckConstraint(
        "operator_role IN ('operator', 'admin')",
        name="ck_approval_decisions_operator_role",
    ),
    PrimaryKeyConstraint("id", name="pk_approval_decisions"),
    UniqueConstraint("draft_id", name="uq_approval_decisions_draft_id"),
)
