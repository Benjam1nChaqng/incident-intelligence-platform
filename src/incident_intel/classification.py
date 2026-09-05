from time import perf_counter
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from incident_intel.auth_failures import extract_auth_failure_evidence
from incident_intel.schemas import EventBundle, LogEvent

ClassificationCategory = Literal[
    "authentication_failure",
    "network_connectivity",
    "endpoint_health",
    "uncategorized",
]


class ClassificationResult(BaseModel):
    provider: str
    category: ClassificationCategory
    confidence: float = Field(ge=0, le=1)
    cited_evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    explanation: str
    model_version: str
    prompt_version: str
    latency_ms: float = Field(ge=0)


class Classifier(Protocol):
    def classify(self, bundle: EventBundle) -> ClassificationResult: ...


class ClassificationRecord(ClassificationResult):
    classification_id: UUID
    incident_id: UUID
    created_at: AwareDatetime


class RulesClassifier:
    provider = "deterministic_rules"
    model_version = "rules-v1"
    prompt_version = "none"

    def classify(self, bundle: EventBundle) -> ClassificationResult:
        started = perf_counter()
        category, confidence, citations, reasons = self._classify_supported_evidence(bundle)
        latency_ms = (perf_counter() - started) * 1000
        return ClassificationResult(
            provider=self.provider,
            category=category,
            confidence=confidence,
            cited_evidence_ids=citations,
            reason_codes=reasons,
            explanation=self._explanation(category, reasons),
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            latency_ms=latency_ms,
        )

    def _classify_supported_evidence(
        self,
        bundle: EventBundle,
    ) -> tuple[ClassificationCategory, float, tuple[str, ...], tuple[str, ...]]:
        auth_evidence = extract_auth_failure_evidence(bundle)
        if auth_evidence.signals:
            citations = tuple(
                log.event_id for log in bundle.logs if self._is_authentication_evidence(log)
            )
            confidence = 0.95 if len(auth_evidence.signals) >= 3 else 0.8
            return (
                "authentication_failure",
                confidence,
                citations,
                auth_evidence.signals,
            )

        network_logs = tuple(log for log in bundle.logs if self._is_network_evidence(log))
        endpoint_logs = tuple(log for log in bundle.logs if self._is_endpoint_evidence(log))
        if network_logs and len(network_logs) >= len(endpoint_logs):
            return (
                "network_connectivity",
                0.85,
                tuple(log.event_id for log in network_logs),
                ("network_or_dns_failure",),
            )
        if endpoint_logs:
            return (
                "endpoint_health",
                0.82,
                tuple(log.event_id for log in endpoint_logs),
                ("endpoint_health_signal",),
            )
        return (
            "uncategorized",
            0.2,
            (),
            ("insufficient_supported_evidence",),
        )

    @staticmethod
    def _is_authentication_evidence(log: LogEvent) -> bool:
        attributes = log.attributes
        message = log.message.lower()
        return bool(
            attributes.get("result") == "denied"
            or attributes.get("lockout") is True
            or isinstance(attributes.get("failure_count"), int)
            or "lockout" in message
        )

    @staticmethod
    def _is_network_evidence(log: LogEvent) -> bool:
        value = f"{log.service} {log.message}".lower()
        return any(
            token in value
            for token in ("dns", "network", "router", "switch", "unreachable", "packet", "latency")
        )

    @staticmethod
    def _is_endpoint_evidence(log: LogEvent) -> bool:
        value = f"{log.service} {log.message}".lower()
        return any(
            token in value
            for token in ("endpoint", "device", "disk", "cpu", "memory", "crash", "antivirus")
        )

    @staticmethod
    def _explanation(
        category: ClassificationCategory,
        reasons: tuple[str, ...],
    ) -> str:
        return f"{category} selected from deterministic evidence rules: {', '.join(reasons)}."
