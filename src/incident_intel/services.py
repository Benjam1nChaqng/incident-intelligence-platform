from dataclasses import dataclass
from uuid import UUID

from incident_intel.approvals import (
    ApprovalRepository,
    Decision,
    DraftRecord,
    build_response_draft,
)
from incident_intel.auth import OperatorClaims, OperatorRole, authorize
from incident_intel.classification import ClassificationRecord
from incident_intel.incidents import (
    IncidentDetail,
    IncidentNotFound,
    IncidentPage,
    IncidentRepository,
)
from incident_intel.ingestion import StorageUnavailable
from incident_intel.jobs import JobRecord, JobRepository


@dataclass(frozen=True)
class IncidentService:
    """Authorizes verified actors before using trusted persistence adapters.

    Authentication belongs at the transport boundary. Authorization also lives
    here so a non-HTTP caller cannot bypass the application's role policy.
    """

    incidents: IncidentRepository
    jobs: JobRepository | None = None
    approvals: ApprovalRepository | None = None

    def list_incidents(
        self,
        actor: OperatorClaims,
        *,
        limit: int = 20,
        cursor: str | None = None,
        status: str | None = None,
        priority: str | None = None,
    ) -> IncidentPage:
        self._require_role(actor, "viewer")
        return self.incidents.list_incidents(
            limit=limit, cursor=cursor, status=status, priority=priority
        )

    def get_incident(self, actor: OperatorClaims, incident_id: UUID) -> IncidentDetail:
        self._require_role(actor, "viewer")
        incident = self.incidents.get_incident(incident_id)
        if incident is None:
            raise IncidentNotFound
        return incident

    def get_job(self, actor: OperatorClaims, job_id: UUID) -> JobRecord | None:
        self._require_role(actor, "viewer")
        if self.jobs is None:
            raise StorageUnavailable
        return self.jobs.get_job(job_id)

    def get_classification(
        self, actor: OperatorClaims, classification_id: UUID
    ) -> ClassificationRecord | None:
        self._require_role(actor, "viewer")
        if self.jobs is None:
            raise StorageUnavailable
        return self.jobs.get_classification(classification_id)

    def create_classification_job(self, actor: OperatorClaims, incident_id: UUID) -> JobRecord:
        self._require_role(actor, "operator")
        if self.jobs is None:
            raise StorageUnavailable
        self.get_incident(actor, incident_id)
        return self.jobs.create_classification_job(incident_id)

    def retry_job(self, actor: OperatorClaims, job_id: UUID) -> JobRecord:
        self._require_role(actor, "admin")
        if self.jobs is None:
            raise StorageUnavailable
        return self.jobs.retry_job(job_id)

    def create_draft(self, actor: OperatorClaims, incident_id: UUID) -> DraftRecord:
        self._require_role(actor, "operator")
        if self.approvals is None:
            raise StorageUnavailable
        incident = self.get_incident(actor, incident_id)
        return self.approvals.create_draft(
            incident_id,
            content=build_response_draft(incident),
            created_by=actor.operator_id,
        )

    def get_draft(self, actor: OperatorClaims, draft_id: UUID) -> DraftRecord | None:
        self._require_role(actor, "viewer")
        if self.approvals is None:
            raise StorageUnavailable
        return self.approvals.get_draft(draft_id)

    def decide(
        self,
        actor: OperatorClaims,
        draft_id: UUID,
        *,
        decision: Decision,
        reason: str | None = None,
    ) -> DraftRecord:
        self._require_role(actor, "operator")
        if self.approvals is None:
            raise StorageUnavailable
        return self.approvals.decide(
            draft_id, decision=decision, operator=actor, reason=reason
        )

    @staticmethod
    def _require_role(actor: OperatorClaims, minimum_role: OperatorRole) -> None:
        if not authorize(actor, minimum_role=minimum_role):
            raise PermissionError("The actor role is not permitted to perform this action.")
