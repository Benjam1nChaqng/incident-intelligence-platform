from typing import Literal

from pydantic import BaseModel

from incident_intel.auth_failures import extract_auth_failure_evidence
from incident_intel.schemas import EventBundle

IncidentCategory = Literal["authentication_failure", "uncategorized"]
ClassificationConfidence = Literal["low", "medium", "high"]
ApprovalStatus = Literal["pending_human_approval"]


class IncidentClassification(BaseModel):
    correlation_id: str
    ticket_id: str
    category: IncidentCategory
    confidence: ClassificationConfidence
    reason_codes: tuple[str, ...]
    summary: str


class RunbookDraft(BaseModel):
    classification: IncidentClassification
    approval_status: ApprovalStatus
    approval_required: bool
    suggested_runbook: str
    operator_notes: str


def classify_incident(bundle: EventBundle) -> IncidentClassification:
    evidence = extract_auth_failure_evidence(bundle)
    if evidence.signals:
        return IncidentClassification(
            correlation_id=bundle.correlation_id,
            ticket_id=bundle.ticket.ticket_id,
            category="authentication_failure",
            confidence=_confidence_for_signals(evidence.signals),
            reason_codes=evidence.signals,
            summary=(
                f"{_confidence_label(_confidence_for_signals(evidence.signals))} confidence "
                f"authentication_failure incident for ticket {bundle.ticket.ticket_id}."
            ),
        )

    return IncidentClassification(
        correlation_id=bundle.correlation_id,
        ticket_id=bundle.ticket.ticket_id,
        category="uncategorized",
        confidence="low",
        reason_codes=(),
        summary=f"Low confidence uncategorized incident for ticket {bundle.ticket.ticket_id}.",
    )


def draft_runbook_response(bundle: EventBundle) -> RunbookDraft:
    classification = classify_incident(bundle)
    return RunbookDraft(
        classification=classification,
        approval_status="pending_human_approval",
        approval_required=True,
        suggested_runbook=_suggested_runbook(classification),
        operator_notes=(
            "Draft only. A human reviewer must approve wording and next actions before any "
            "response is sent or external system is updated."
        ),
    )


def _confidence_for_signals(signals: tuple[str, ...]) -> ClassificationConfidence:
    if "account_lockout" in signals and "repeated_failures" in signals:
        return "high"
    if "mfa_denied" in signals:
        return "medium"
    return "low"


def _confidence_label(confidence: ClassificationConfidence) -> str:
    return confidence.capitalize()


def _suggested_runbook(classification: IncidentClassification) -> str:
    if classification.category == "authentication_failure":
        return (
            "Verify the synthetic user's identity, review MFA challenge history, "
            "confirm the lockout window, reset authentication factors if policy allows, "
            "and monitor for repeated failures before closing the ticket."
        )
    return (
        "Review the ticket context and correlated logs, collect missing evidence, "
        "and assign a human analyst before drafting an external response."
    )
