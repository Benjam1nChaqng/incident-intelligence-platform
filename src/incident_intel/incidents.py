import base64
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ValidationError


class InvalidCursor(Exception):  # noqa: N818 - stable domain name used by the API contract
    """Raised when a collection cursor cannot be decoded safely."""


class IncidentNotFound(Exception):  # noqa: N818 - stable domain name used by the API contract
    """Raised when an incident identifier does not exist."""


class IncidentSummary(BaseModel):
    incident_id: UUID
    correlation_id: str
    status: str
    priority: str
    summary: str
    created_at: AwareDatetime
    updated_at: AwareDatetime


class IncidentPage(BaseModel):
    items: tuple[IncidentSummary, ...]
    next_cursor: str | None


class TicketDetail(BaseModel):
    ticket_id: str
    subject: str
    description: str
    priority: str
    source: str
    requester_role: str
    created_at: AwareDatetime
    tags: tuple[str, ...]


class EvidenceDetail(BaseModel):
    event_id: str
    observed_at: AwareDatetime
    service: str
    severity: str
    message: str
    synthetic_user_id: str
    attributes: dict[str, str | int | float | bool | None]


class IncidentDetail(IncidentSummary):
    ticket: TicketDetail
    evidence: tuple[EvidenceDetail, ...]


class IncidentRepository(Protocol):
    def list_incidents(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        status: str | None = None,
        priority: str | None = None,
    ) -> IncidentPage: ...

    def get_incident(self, incident_id: UUID) -> IncidentDetail | None: ...


@dataclass(frozen=True)
class EmptyIncidentRepository:
    def list_incidents(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        status: str | None = None,
        priority: str | None = None,
    ) -> IncidentPage:
        if cursor is not None:
            decode_incident_cursor(cursor)
        return IncidentPage(items=(), next_cursor=None)

    def get_incident(self, incident_id: UUID) -> IncidentDetail | None:
        return None


class _CursorPayload(BaseModel):
    created_at: AwareDatetime
    incident_id: UUID


def encode_incident_cursor(item: IncidentSummary) -> str:
    payload = _CursorPayload(
        created_at=item.created_at,
        incident_id=item.incident_id,
    ).model_dump_json()
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_incident_cursor(cursor: str) -> _CursorPayload:
    if not cursor or len(cursor) > 512:
        raise InvalidCursor
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        return _CursorPayload.model_validate_json(decoded)
    except (ValueError, ValidationError):
        raise InvalidCursor from None
