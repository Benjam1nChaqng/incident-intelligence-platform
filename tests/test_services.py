from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest

from incident_intel.approvals import ApprovalRepository, build_response_draft
from incident_intel.auth import OperatorClaims
from incident_intel.incidents import IncidentDetail, IncidentNotFound, IncidentRepository
from incident_intel.ingestion import StorageUnavailable
from incident_intel.jobs import JobRepository
from incident_intel.services import IncidentService


@pytest.fixture
def service() -> IncidentService:
    return IncidentService(
        incidents=Mock(spec=IncidentRepository),
        jobs=Mock(spec=JobRepository),
        approvals=Mock(spec=ApprovalRepository),
    )


@pytest.fixture
def viewer() -> OperatorClaims:
    return OperatorClaims(operator_id="synthetic-viewer-1", role="viewer")


@pytest.fixture
def operator() -> OperatorClaims:
    return OperatorClaims(operator_id="synthetic-operator-1", role="operator")


@pytest.mark.parametrize("action", ["classification", "draft", "approve", "reject"])
def test_viewer_cannot_write_even_without_an_http_route(
    action: str, service: IncidentService, viewer: OperatorClaims
) -> None:
    target_id = uuid4()

    with pytest.raises(PermissionError):
        if action == "classification":
            service.create_classification_job(viewer, target_id)
        elif action == "draft":
            service.create_draft(viewer, target_id)
        else:
            service.decide(
                viewer,
                target_id,
                decision="approved" if action == "approve" else "rejected",
                reason="Synthetic review.",
            )

    assert service.incidents.mock_calls == []
    assert service.jobs.mock_calls == []
    assert service.approvals.mock_calls == []


def test_viewer_can_read_incidents_jobs_and_drafts(
    service: IncidentService, viewer: OperatorClaims
) -> None:
    target_id = uuid4()
    assert service.list_incidents(viewer, limit=5) is service.incidents.list_incidents.return_value
    assert service.get_incident(viewer, target_id) is service.incidents.get_incident.return_value
    assert service.get_job(viewer, target_id) is service.jobs.get_job.return_value
    assert service.get_draft(viewer, target_id) is service.approvals.get_draft.return_value
    service.incidents.list_incidents.assert_called_once_with(
        limit=5, cursor=None, status=None, priority=None
    )


def test_missing_incident_prevents_job_or_draft_creation(
    service: IncidentService, operator: OperatorClaims
) -> None:
    service.incidents.get_incident.return_value = None
    target_id = uuid4()

    for action in (service.get_incident, service.create_classification_job, service.create_draft):
        with pytest.raises(IncidentNotFound):
            action(operator, target_id)

    assert service.jobs.mock_calls == []
    assert service.approvals.mock_calls == []


@pytest.mark.parametrize("role", ["operator", "admin"])
def test_draft_uses_stored_evidence_and_verified_actor(service: IncidentService, role: str) -> None:
    actor = OperatorClaims(operator_id="synthetic-reviewer-1", role=role)
    incident_id = uuid4()
    now = datetime.now(UTC)
    incident = IncidentDetail(
        incident_id=incident_id,
        correlation_id="INC-SYNTHETIC-001",
        status="open",
        priority="high",
        summary="Synthetic sign-in failure.",
        created_at=now,
        updated_at=now,
        ticket={
            "ticket_id": "TICKET-SYNTHETIC-001",
            "subject": "Synthetic sign-in failure",
            "description": "A synthetic user cannot sign in.",
            "priority": "high",
            "source": "synthetic",
            "requester_role": "staff",
            "created_at": now,
            "tags": (),
        },
        evidence=(),
    )
    service.incidents.get_incident.return_value = incident

    draft = service.create_draft(actor, incident_id)
    decided = service.decide(actor, uuid4(), decision="approved", reason="Reviewed evidence.")

    assert draft is service.approvals.create_draft.return_value
    assert decided is service.approvals.decide.return_value
    service.approvals.create_draft.assert_called_once_with(
        incident_id, content=build_response_draft(incident), created_by=actor.operator_id
    )
    assert service.approvals.decide.call_args.kwargs["operator"] == actor


@pytest.mark.parametrize(
    "action", ["get_job", "create_classification_job", "get_draft", "create_draft"]
)
def test_unconfigured_repository_is_reported_as_unavailable(
    action: str, operator: OperatorClaims
) -> None:
    service = IncidentService(incidents=Mock(spec=IncidentRepository))

    with pytest.raises(StorageUnavailable):
        getattr(service, action)(operator, uuid4())

    assert service.incidents.mock_calls == []


def test_unconfigured_approval_decision_is_unavailable(operator: OperatorClaims) -> None:
    service = IncidentService(incidents=Mock(spec=IncidentRepository))

    with pytest.raises(StorageUnavailable):
        service.decide(operator, uuid4(), decision="rejected")


def test_optional_reads_preserve_missing_result(
    service: IncidentService, viewer: OperatorClaims
) -> None:
    service.jobs.get_job.return_value = None
    service.approvals.get_draft.return_value = None

    assert service.get_job(viewer, uuid4()) is None
    assert service.get_draft(viewer, uuid4()) is None


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_retry_requires_admin_before_any_storage_call(service: IncidentService, role: str) -> None:
    actor = OperatorClaims(operator_id="synthetic-reviewer-1", role=role)

    with pytest.raises(PermissionError):
        service.retry_job(actor, uuid4())

    assert service.incidents.mock_calls == []
    assert service.jobs.mock_calls == []
    assert service.approvals.mock_calls == []


def test_admin_can_retry_failed_job(service: IncidentService) -> None:
    admin = OperatorClaims(operator_id="synthetic-admin-1", role="admin")
    job_id = uuid4()

    result = service.retry_job(admin, job_id)

    assert result is service.jobs.retry_job.return_value
    service.jobs.retry_job.assert_called_once_with(job_id)


def test_viewer_can_read_persisted_classification(
    service: IncidentService, viewer: OperatorClaims
) -> None:
    classification_id = uuid4()

    result = service.get_classification(viewer, classification_id)

    assert result is service.jobs.get_classification.return_value
    service.jobs.get_classification.assert_called_once_with(classification_id)
