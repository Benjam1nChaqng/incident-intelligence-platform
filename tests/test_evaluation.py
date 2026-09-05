from pathlib import Path

import pytest

from incident_intel.classification import (
    ClassificationCategory,
    ClassificationResult,
    RulesClassifier,
)
from incident_intel.evaluate import EvaluationCase, _citations_are_valid, evaluate_dataset
from incident_intel.schemas import EventBundle

DATASET_PATH = Path(__file__).parents[1] / "data" / "evaluation_v1.json"


def test_deterministic_evaluation_reports_measured_quality_and_latency() -> None:
    report = evaluate_dataset(DATASET_PATH)

    assert report.dataset_version == "evaluation-v1"
    assert report.provider == "deterministic_rules"
    assert report.model_version == "rules-v1"
    assert report.case_count == 12
    assert report.macro_f1 == 1.0
    assert report.abstention_rate == 0.25
    assert report.unsupported_evidence_rate == 0.0
    assert report.citation_validity == 1.0
    assert report.median_latency_ms >= 0
    assert report.p95_latency_ms >= report.median_latency_ms
    assert set(report.per_category) == {
        "authentication_failure",
        "network_connectivity",
        "endpoint_health",
        "uncategorized",
    }
    assert all(metrics.f1 == 1.0 for metrics in report.per_category.values())


@pytest.mark.parametrize(
    ("category", "citation_ids", "expected"),
    [
        ("network_connectivity", ("EVAL-EVENT-0001",), True),
        ("network_connectivity", (), False),
        ("network_connectivity", ("invented-event",), False),
        ("network_connectivity", ("EVAL-EVENT-0001", "invented-event"), False),
        ("uncategorized", (), True),
        ("uncategorized", ("invented-event",), False),
    ],
)
def test_citation_check_requires_existing_ids_and_nonempty_predictions(
    category: ClassificationCategory, citation_ids: tuple[str, ...], expected: bool
) -> None:
    bundle = EvaluationCase(
        case_id="synthetic-citation-check",
        expected_category="network_connectivity",
        service="network",
        message="Synthetic network failure",
        attributes={},
    ).to_bundle(1)
    result = ClassificationResult(
        provider="synthetic-test",
        category=category,
        confidence=0.9,
        cited_evidence_ids=citation_ids,
        reason_codes=("synthetic-test",),
        explanation="Synthetic result for citation-ID validation only.",
        model_version="synthetic-test",
        prompt_version="none",
        latency_ms=0,
    )

    assert _citations_are_valid(bundle, result) is expected


def test_evaluation_counts_uncited_predictions_as_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UncitedClassifier(RulesClassifier):
        def classify(self, bundle: EventBundle) -> ClassificationResult:
            result = super().classify(bundle)
            return result.model_copy(update={"cited_evidence_ids": ()})

    monkeypatch.setattr("incident_intel.evaluate.RulesClassifier", UncitedClassifier)

    report = evaluate_dataset(DATASET_PATH)

    # Nine predictions lack citations; the three empty abstentions remain valid.
    assert report.unsupported_evidence_rate == 0.75
    assert report.citation_validity == 0.25
    assert report.abstention_rate == 0.25
