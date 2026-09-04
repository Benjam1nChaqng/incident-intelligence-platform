from datetime import timedelta
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from incident_intel.schemas import EventBundle


class IncidentFingerprint(BaseModel):
    incident_id: UUID
    correlation_id: str
    observed_from: AwareDatetime
    observed_to: AwareDatetime
    synthetic_user_ids: tuple[str, ...]
    services: tuple[str, ...]


class CorrelationResult(BaseModel):
    incident_id: UUID | None
    score: int = Field(ge=0, le=100)
    reason_codes: tuple[str, ...]
    abstained: bool


def correlate_bundle(
    bundle: EventBundle,
    candidates: tuple[IncidentFingerprint, ...],
    *,
    time_window: timedelta = timedelta(minutes=15),
    threshold: int = 60,
) -> CorrelationResult:
    exact_matches = sorted(
        (
            candidate
            for candidate in candidates
            if candidate.correlation_id == bundle.correlation_id
        ),
        key=lambda candidate: str(candidate.incident_id),
    )
    if exact_matches:
        return CorrelationResult(
            incident_id=exact_matches[0].incident_id,
            score=100,
            reason_codes=("exact_correlation_id",),
            abstained=False,
        )

    scored = sorted(
        (_score_candidate(bundle, candidate, time_window) for candidate in candidates),
        key=lambda item: (-item[0], str(item[1].incident_id)),
    )
    if not scored:
        return CorrelationResult(
            incident_id=None,
            score=0,
            reason_codes=("no_correlation_candidates",),
            abstained=True,
        )

    best_score, best_candidate, reasons = scored[0]
    if best_score < threshold:
        return CorrelationResult(
            incident_id=None,
            score=best_score,
            reason_codes=("below_correlation_threshold",),
            abstained=True,
        )
    return CorrelationResult(
        incident_id=best_candidate.incident_id,
        score=best_score,
        reason_codes=reasons,
        abstained=False,
    )


def _score_candidate(
    bundle: EventBundle,
    candidate: IncidentFingerprint,
    time_window: timedelta,
) -> tuple[int, IncidentFingerprint, tuple[str, ...]]:
    score = 0
    reasons: list[str] = []
    bundle_users = {log.synthetic_user_id for log in bundle.logs}
    bundle_services = {log.service for log in bundle.logs}
    if bundle_users.intersection(candidate.synthetic_user_ids):
        score += 45
        reasons.append("synthetic_identity_match")
    if bundle_services.intersection(candidate.services):
        score += 25
        reasons.append("service_match")

    bundle_start = min(log.observed_at for log in bundle.logs)
    bundle_end = max(log.observed_at for log in bundle.logs)
    if (
        bundle_start <= candidate.observed_to + time_window
        and bundle_end >= candidate.observed_from - time_window
    ):
        score += 20
        reasons.append("time_window_match")
    return score, candidate, tuple(reasons)
