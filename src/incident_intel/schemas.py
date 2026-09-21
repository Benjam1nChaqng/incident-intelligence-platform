from typing import Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Priority = Literal["low", "medium", "high", "urgent"]
TicketSource = Literal["helpdesk", "email", "chat", "monitoring"]
LogSeverity = Literal["debug", "info", "warning", "error", "critical"]


class SupportTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str = Field(min_length=3, max_length=64)
    subject: str = Field(min_length=8, max_length=160)
    description: str = Field(min_length=20, max_length=2_000)
    priority: Priority
    source: TicketSource
    requester_role: str = Field(min_length=2, max_length=80)
    created_at: AwareDatetime
    tags: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> Any:
        if value is None:
            return ()
        return value


class LogEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=3, max_length=64)
    observed_at: AwareDatetime
    service: str = Field(min_length=2, max_length=80)
    severity: LogSeverity
    message: str = Field(min_length=8, max_length=1_000)
    synthetic_user_id: str = Field(min_length=3, max_length=80)
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("synthetic_user_id")
    @classmethod
    def reject_raw_user_identifier(cls, value: str) -> str:
        if "@" in value or "\\" in value:
            raise ValueError(
                "synthetic_user_id must be synthetic and must not contain raw identifiers"
            )
        return value


class EventBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation_id: str = Field(min_length=6, max_length=80)
    ticket: SupportTicket
    logs: tuple[LogEvent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_event_ids(self) -> Self:
        event_ids = [log.event_id for log in self.logs]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event_id values must be unique within an event bundle")
        return self
