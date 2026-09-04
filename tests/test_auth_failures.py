import json
from pathlib import Path

import httpx
import pytest

from incident_intel.auth_failures import extract_auth_failure_evidence
from incident_intel.schemas import EventBundle

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "auth_failure_bundle.json"


def load_bundle() -> EventBundle:
    return EventBundle.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


def load_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_extract_auth_failure_evidence_from_mfa_denial_and_lockout() -> None:
    evidence = extract_auth_failure_evidence(load_bundle())

    assert evidence.correlation_id == "INC-AUTH-0001"
    assert evidence.ticket_id == "TCK-1001"
    assert evidence.category == "authentication_failure"
    assert evidence.risk_level == "high"
    assert evidence.affected_synthetic_users == ("user-auth-001",)
    assert evidence.signals == (
        "mfa_denied",
        "account_lockout",
        "repeated_failures",
    )
    assert evidence.support_summary == (
        "Synthetic user user-auth-001 hit MFA denial and account lockout signals "
        "across 2 identity-provider logs."
    )


@pytest.mark.anyio
async def test_preview_auth_failure_evidence_endpoint_returns_json_summary(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/investigations/auth-failure-preview", json=load_payload())

    assert response.status_code == 200
    assert response.json() == {
        "correlation_id": "INC-AUTH-0001",
        "ticket_id": "TCK-1001",
        "category": "authentication_failure",
        "risk_level": "high",
        "affected_synthetic_users": ["user-auth-001"],
        "signals": ["mfa_denied", "account_lockout", "repeated_failures"],
        "support_summary": (
            "Synthetic user user-auth-001 hit MFA denial and account lockout signals "
            "across 2 identity-provider logs."
        ),
    }
