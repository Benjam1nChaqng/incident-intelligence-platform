from threading import Lock

from pydantic import BaseModel, Field

OPERATION_NAMES = (
    "accepted",
    "duplicate",
    "conflict",
    "rejected",
    "retried",
    "failed",
    "approved",
)


class LatencySummary(BaseModel):
    count: int = Field(ge=0)
    mean_ms: float = Field(ge=0)
    max_ms: float = Field(ge=0)


class MetricsSnapshot(BaseModel):
    counters: dict[str, int]
    request_latency: LatencySummary


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters = {name: 0 for name in OPERATION_NAMES}
        self._request_count = 0
        self._request_total_ms = 0.0
        self._request_max_ms = 0.0

    def increment(self, operation: str, *, amount: int = 1) -> None:
        if operation not in self._counters:
            raise ValueError("unsupported operation metric")
        if amount < 1:
            raise ValueError("metric amount must be positive")
        with self._lock:
            self._counters[operation] += amount

    def observe_request(self, latency_ms: float) -> None:
        if latency_ms < 0:
            raise ValueError("request latency cannot be negative")
        with self._lock:
            self._request_count += 1
            self._request_total_ms += latency_ms
            self._request_max_ms = max(self._request_max_ms, latency_ms)

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            mean_ms = (
                self._request_total_ms / self._request_count if self._request_count else 0.0
            )
            return MetricsSnapshot(
                counters=dict(self._counters),
                request_latency=LatencySummary(
                    count=self._request_count,
                    mean_ms=mean_ms,
                    max_ms=self._request_max_ms,
                ),
            )
