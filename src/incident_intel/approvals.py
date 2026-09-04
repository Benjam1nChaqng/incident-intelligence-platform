from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from incident_intel.auth import OperatorClaims
from incident_intel.incidents import IncidentDetail

DraftStatus = Literal["pending_review", "approved", "rejected"]
Decision = Literal["approved", "rejected"]


class DraftNotFound(Exception):  # noqa: N818 - stable domain name used by the API contract
    """Raised when a response draft does not exist."""


class DraftStateConflict(Exception):  # noqa: N818 - stable domain name used by the API contract
    """Raised when a response draft already has a decision."""


class ApprovalDecisionRecord(BaseModel):
    decision_id: UUID
    draft_id: UUID
    decision: Decision
    operator_id: str
    operator_role: Literal["operator", "admin"]
    reason: str | None
    created_at: AwareDatetime


class DraftRecord(BaseModel):
    draft_id: UUID
    incident_id: UUID
    content: str
    status: DraftStatus
    created_by: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    decision: ApprovalDecisionRecord | None = None


class DecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ApprovalRepository(Protocol):
    def create_draft(
        self,
        incident_id: UUID,
        *,
        content: str,
        created_by: str,
    ) -> DraftRecord: ...

    def get_draft(self, draft_id: UUID) -> DraftRecord | None: ...

    def decide(
        self,
        draft_id: UUID,
        *,
        decision: Decision,
        operator: OperatorClaims,
        reason: str | None,
    ) -> DraftRecord: ...


def build_response_draft(incident: IncidentDetail) -> str:
    evidence_ids = ", ".join(item.event_id for item in incident.evidence)
    return (
        f"Review incident {incident.correlation_id}: {incident.summary}. "
        f"Evidence: {evidence_ids}. "
        "Draft only. Verify the cited evidence and choose an operator-approved next action."
    )
