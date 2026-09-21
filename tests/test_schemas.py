import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from incident_intel.schemas import EventBundle, LogEvent, SupportTicket

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "auth_failure_bundle.json"


def test_support_ticket_accepts_synthetic_customer_issue() -> None:
    ticket = SupportTicket.model_validate(
        {
            "ticket_id": "TCK-1001",
            "subject": "User cannot sign in after password reset",
            "description": "Synthetic user reports repeated sign-in failures after a reset.",
            "priority": "high",
            "source": "helpdesk",
            "requester_role": "Finance Manager",
            "created_at": "2026-08-26T15:21:00Z",
            "tags": ["authentication", "password-reset"],
        }
    )

    assert ticket.ticket_id == "TCK-1001"
    assert ticket.created_at == datetime(2026, 8, 26, 15, 21, tzinfo=UTC)
    assert ticket.tags == ("authentication", "password-reset")


def test_log_event_requires_synthetic_redaction_marker_for_user_identifiers() -> None:
    with pytest.raises(ValidationError, match="synthetic_user_id"):
        LogEvent.model_validate(
            {
                "event_id": "LOG-2001",
                "observed_at": "2026-08-26T15:22:04Z",
                "service": "identity-provider",
                "severity": "warning",
                "message": "Failed login for finance.manager@example.com",
                "synthetic_user_id": "finance.manager@example.com",
                "attributes": {"ip": "203.0.113.10"},
            }
        )


def test_event_bundle_links_ticket_and_logs_by_correlation_id() -> None:
    bundle = EventBundle.model_validate(
        {
            "correlation_id": "INC-AUTH-0001",
            "ticket": {
                "ticket_id": "TCK-1001",
                "subject": "User cannot sign in after password reset",
                "description": "Synthetic user reports repeated sign-in failures after a reset.",
                "priority": "high",
                "source": "helpdesk",
                "requester_role": "Finance Manager",
                "created_at": "2026-08-26T15:21:00Z",
                "tags": ["authentication"],
            },
            "logs": [
                {
                    "event_id": "LOG-2001",
                    "observed_at": "2026-08-26T15:22:04Z",
                    "service": "identity-provider",
                    "severity": "warning",
                    "message": "Synthetic user failed MFA challenge.",
                    "synthetic_user_id": "user-auth-001",
                    "attributes": {"auth_method": "mfa_push", "result": "denied"},
                }
            ],
        }
    )

    assert bundle.correlation_id == "INC-AUTH-0001"
    assert bundle.ticket.priority == "high"
    assert bundle.logs[0].attributes["result"] == "denied"


def test_auth_failure_fixture_matches_event_bundle_schema() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    bundle = EventBundle.model_validate(payload)

    assert bundle.correlation_id == "INC-AUTH-0001"
    assert len(bundle.logs) == 2


@pytest.mark.parametrize("tags", ["authentication", {"authentication": True}, 42, True, 1.5])
def test_support_ticket_rejects_invalid_tag_containers(tags: object) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["ticket"]
    payload["tags"] = tags

    with pytest.raises(ValidationError, match="tags"):
        SupportTicket.model_validate(payload)


@pytest.mark.parametrize("tags", [None, [], ["authentication", "password-reset"]])
def test_support_ticket_preserves_supported_tag_inputs(tags: object) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["ticket"]
    payload["tags"] = tags

    assert SupportTicket.model_validate(payload).tags == tuple(tags or ())


def test_support_ticket_defaults_missing_tags_to_empty() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["ticket"]
    payload.pop("tags", None)

    assert SupportTicket.model_validate(payload).tags == ()


def test_support_ticket_rejects_naive_created_at() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["ticket"]
    payload["created_at"] = "2026-08-26T15:21:00"

    with pytest.raises(ValidationError, match="created_at"):
        SupportTicket.model_validate(payload)


def test_log_event_rejects_naive_observed_at() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["logs"][0]
    payload["observed_at"] = "2026-08-26T15:22:04"

    with pytest.raises(ValidationError, match="observed_at"):
        LogEvent.model_validate(payload)


def test_event_bundle_rejects_duplicate_evidence_ids() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["logs"][1]["event_id"] = payload["logs"][0]["event_id"]

    with pytest.raises(ValidationError, match="event_id values must be unique"):
        EventBundle.model_validate(payload)
