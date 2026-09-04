from pathlib import Path

from incident_intel.evaluate import evaluate_dataset

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
