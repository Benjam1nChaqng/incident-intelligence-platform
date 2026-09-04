import json
from pathlib import Path

from incident_intel.classification import RulesClassifier
from incident_intel.schemas import EventBundle

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "auth_failure_bundle.json"


def load_bundle() -> EventBundle:
    return EventBundle.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


def bundle_with_log_signals(*, service: str, message: str) -> EventBundle:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["logs"] = [payload["logs"][0]]
    payload["logs"][0]["service"] = service
    payload["logs"][0]["message"] = message
    payload["logs"][0]["attributes"] = {}
    return EventBundle.model_validate(payload)


def test_rules_classifier_explains_authentication_failure_with_valid_citations() -> None:
    result = RulesClassifier().classify(load_bundle())

    assert result.provider == "deterministic_rules"
    assert result.category == "authentication_failure"
    assert result.confidence == 0.95
    assert result.cited_evidence_ids == ("LOG-2001", "LOG-2002")
    assert result.reason_codes == ("mfa_denied", "account_lockout", "repeated_failures")
    assert result.model_version == "rules-v1"
    assert result.prompt_version == "none"
    assert result.latency_ms >= 0


def test_rules_classifier_distinguishes_network_and_endpoint_incidents() -> None:
    network = RulesClassifier().classify(
        bundle_with_log_signals(
            service="dns-resolver",
            message="DNS lookup timeout made the network unreachable.",
        )
    )
    endpoint = RulesClassifier().classify(
        bundle_with_log_signals(
            service="endpoint-agent",
            message="Endpoint disk health warning detected.",
        )
    )

    assert network.category == "network_connectivity"
    assert network.cited_evidence_ids == ("LOG-2001",)
    assert endpoint.category == "endpoint_health"
    assert endpoint.cited_evidence_ids == ("LOG-2001",)


def test_rules_classifier_abstains_when_evidence_is_unsupported() -> None:
    result = RulesClassifier().classify(
        bundle_with_log_signals(
            service="business-application",
            message="Synthetic user requested a general information update.",
        )
    )

    assert result.category == "uncategorized"
    assert result.confidence == 0.2
    assert result.cited_evidence_ids == ()
    assert result.reason_codes == ("insufficient_supported_evidence",)
