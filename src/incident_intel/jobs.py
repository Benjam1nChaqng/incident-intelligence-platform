from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from incident_intel.classification import ClassificationRecord, ClassificationResult

JobState = Literal["pending", "processing", "retry_pending", "completed", "failed"]


class JobNotFound(Exception):  # noqa: N818 - stable domain name used by the API contract
    """Raised when a job identifier does not exist."""


class InvalidJobState(Exception):  # noqa: N818 - stable domain name used by the API contract
    """Raised when a worker transition does not match the persisted state."""


class RetryableJobError(Exception):
    """Marks a transient classifier failure that the worker may retry."""


class JobRecord(BaseModel):
    job_id: UUID
    incident_id: UUID
    job_type: str
    state: JobState
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(gt=0)
    next_attempt_at: AwareDatetime
    claimed_at: AwareDatetime | None
    claimed_by: str | None
    claim_token: UUID | None = Field(exclude=True)
    completed_at: AwareDatetime | None
    result_id: UUID | None
    last_error_class: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class JobRepository(Protocol):
    def create_classification_job(
        self,
        incident_id: UUID,
        *,
        max_attempts: int = 3,
    ) -> JobRecord: ...

    def get_job(self, job_id: UUID) -> JobRecord | None: ...

    def get_classification(self, classification_id: UUID) -> ClassificationRecord | None: ...

    def retry_job(self, job_id: UUID) -> JobRecord: ...

    def claim_jobs(
        self,
        *,
        worker_id: str,
        limit: int = 10,
        now: datetime | None = None,
    ) -> tuple[JobRecord, ...]: ...

    def complete_classification(
        self,
        job_id: UUID,
        result: ClassificationResult,
        *,
        claim_token: UUID,
        now: datetime | None = None,
    ) -> JobRecord: ...

    def fail_job(
        self,
        job_id: UUID,
        error_class: str,
        *,
        claim_token: UUID,
        retryable: bool,
        now: datetime | None = None,
    ) -> JobRecord: ...


def retry_delay(attempt_count: int) -> timedelta:
    seconds = min(300, 10 * (2 ** min(5, max(0, attempt_count - 1))))
    return timedelta(seconds=seconds)


def utc_now() -> datetime:
    return datetime.now(UTC)
