import json
from pathlib import Path

import httpx
import pytest

from incident_intel.runbooks import draft_runbook_response
from incident_intel.schemas import EventBundle

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "auth_failure_bundle.json"


def load_bundle() -> EventBundle:
    return EventBundle.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


def load_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_draft_runbook_response_requires_human_approval() -> None:
    draft = draft_runbook_response(load_bundle())

    assert draft.classification.category == "authentication_failure"
    assert draft.classification.confidence == "high"
    assert draft.classification.reason_codes == (
        "mfa_denied",
        "account_lockout",
        "repeated_failures",
    )
    assert draft.approval_status == "pending_human_approval"
    assert draft.approval_required is True
    assert draft.suggested_runbook == (
        "Verify the synthetic user's identity, review MFA challenge history, "
        "confirm the lockout window, reset authentication factors if policy allows, "
        "and monitor for repeated failures before closing the ticket."
    )
    assert draft.operator_notes == (
        "Draft only. A human reviewer must approve wording and next actions before any response "
        "is sent or external system is updated."
    )


@pytest.mark.anyio
async def test_preview_runbook_draft_endpoint_returns_unapproved_draft(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/investigations/runbook-draft-preview", json=load_payload())

    assert response.status_code == 200
    assert response.json()["approval_status"] == "pending_human_approval"
    assert response.json()["approval_required"] is True
    assert response.json()["classification"]["summary"] == (
        "High confidence authentication_failure incident for ticket TCK-1001."
    )
