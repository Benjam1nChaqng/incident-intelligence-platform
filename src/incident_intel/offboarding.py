"""Local synthetic offboarding mapping, not a Google Workspace API adapter."""

from datetime import UTC
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from incident_intel.schemas import EventBundle, LogEvent, SupportTicket

SyntheticUserId = Annotated[
    str, Field(pattern=r"^synthetic-user-[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
]
SyntheticEndpointId = Annotated[
    str, Field(pattern=r"^synthetic-endpoint-[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
]
EventId = Annotated[str, Field(min_length=3, max_length=64)]


class _DisabledIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: EventId
    synthetic_user_id: SyntheticUserId
    state: Literal["disabled"]
    disabled_at: AwareDatetime


class _LinkedEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    synthetic_endpoint_id: SyntheticEndpointId
    assigned_synthetic_user_id: SyntheticUserId


class _AccessEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: EventId
    observed_at: AwareDatetime
    synthetic_user_id: SyntheticUserId
    synthetic_endpoint_id: SyntheticEndpointId
    result: Literal["allowed", "denied"]


class _OffboardingFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_format: Literal["synthetic-google-workspace-offboarding-v1"]
    correlation_id: str
    ticket: SupportTicket
    identity: _DisabledIdentity
    endpoint: _LinkedEndpoint
    access_events: tuple[_AccessEvent, ...] = Field(min_length=1)


def adapt_offboarding_fixture(payload: dict[str, object]) -> EventBundle:
    """Validate one offline incident and normalize exact repeats for ingestion replay.

    IDs come from the fixture. Conflicting event IDs, missing identities, unrelated
    endpoints, and access at or before disablement are rejected, never inferred.
    """
    source = _OffboardingFixture.model_validate(payload)
    identity, endpoint = source.identity, source.endpoint
    if endpoint.assigned_synthetic_user_id != identity.synthetic_user_id:
        raise ValueError("endpoint owner must link to the disabled identity")

    events_by_id: dict[str, _AccessEvent] = {}
    for event in source.access_events:
        if event.synthetic_user_id != identity.synthetic_user_id:
            raise ValueError("access identity must link to the disabled identity")
        if event.synthetic_endpoint_id != endpoint.synthetic_endpoint_id:
            raise ValueError("access endpoint must link to the assigned endpoint")
        if event.observed_at <= identity.disabled_at:
            raise ValueError("access must occur strictly after disablement")
        if event.event_id == identity.event_id:
            raise ValueError("access event_id must differ from the disablement event_id")
        existing = events_by_id.get(event.event_id)
        if existing is not None and existing != event:
            raise ValueError("conflicting duplicate event_id in synthetic access events")
        events_by_id[event.event_id] = event

    logs = [
        LogEvent(
            event_id=identity.event_id,
            observed_at=identity.disabled_at.astimezone(UTC),
            service="synthetic-google-workspace",
            severity="info",
            message="Synthetic identity marked disabled in the offline offboarding fixture.",
            synthetic_user_id=identity.synthetic_user_id,
            attributes={
                "event_type": "identity_disabled",
                "identity_state": identity.state,
                "synthetic_endpoint_id": endpoint.synthetic_endpoint_id,
                "fixture_only": True,
            },
        )
    ]
    # Stable event ordering and UTC serialization preserve the existing ingestion hash.
    for event in sorted(events_by_id.values(), key=lambda item: (item.observed_at, item.event_id)):
        logs.append(
            LogEvent(
                event_id=event.event_id,
                observed_at=event.observed_at.astimezone(UTC),
                service="synthetic-google-workspace",
                severity="error" if event.result == "allowed" else "warning",
                message=f"Synthetic access attempt recorded as {event.result} after disablement.",
                synthetic_user_id=event.synthetic_user_id,
                attributes={
                    "event_type": "access_attempt",
                    "result": event.result,
                    "disabled_event_id": identity.event_id,
                    "synthetic_endpoint_id": event.synthetic_endpoint_id,
                    "fixture_only": True,
                },
            )
        )

    return EventBundle(
        correlation_id=source.correlation_id,
        ticket=source.ticket.model_copy(
            update={"created_at": source.ticket.created_at.astimezone(UTC)}
        ),
        logs=tuple(logs),
    )
