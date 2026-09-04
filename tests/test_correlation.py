from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from incident_intel.correlation import IncidentFingerprint, correlate_bundle
from incident_intel.schemas import EventBundle

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "auth_failure_bundle.json"


def load_bundle() -> EventBundle:
    return EventBundle.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


def fingerprint(
    incident_id: str,
    *,
    correlation_id: str,
    users: tuple[str, ...] = (),
    services: tuple[str, ...] = (),
    observed_at: datetime = datetime(2026, 8, 26, 15, 22, tzinfo=UTC),
) -> IncidentFingerprint:
    return IncidentFingerprint(
        incident_id=UUID(incident_id),
        correlation_id=correlation_id,
        observed_from=observed_at,
        observed_to=observed_at + timedelta(minutes=2),
        synthetic_user_ids=users,
        services=services,
    )


def test_exact_correlation_id_always_wins() -> None:
    exact = fingerprint(
        "00000000-0000-0000-0000-000000000001",
        correlation_id="INC-AUTH-0001",
    )
    stronger_attributes = fingerprint(
        "00000000-0000-0000-0000-000000000002",
        correlation_id="INC-OTHER-0002",
        users=("user-auth-001",),
        services=("identity-provider",),
    )

    result = correlate_bundle(load_bundle(), (stronger_attributes, exact))

    assert result.incident_id == exact.incident_id
    assert result.score == 100
    assert result.reason_codes == ("exact_correlation_id",)
    assert result.abstained is False


def test_scored_correlation_records_contributing_rules() -> None:
    candidate = fingerprint(
        "00000000-0000-0000-0000-000000000003",
        correlation_id="INC-OTHER-0003",
        users=("user-auth-001",),
        services=("identity-provider",),
    )

    result = correlate_bundle(load_bundle(), (candidate,))

    assert result.incident_id == candidate.incident_id
    assert result.score == 90
    assert result.reason_codes == (
        "synthetic_identity_match",
        "service_match",
        "time_window_match",
    )
    assert result.abstained is False


def test_low_confidence_correlation_abstains() -> None:
    weak_candidate = fingerprint(
        "00000000-0000-0000-0000-000000000004",
        correlation_id="INC-OTHER-0004",
        services=("identity-provider",),
    )

    result = correlate_bundle(load_bundle(), (weak_candidate,))

    assert result.incident_id is None
    assert result.score == 45
    assert result.reason_codes == ("below_correlation_threshold",)
    assert result.abstained is True
