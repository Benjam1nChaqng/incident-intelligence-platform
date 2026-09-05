import argparse
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

from pydantic import AwareDatetime, BaseModel

from incident_intel.classification import (
    ClassificationCategory,
    ClassificationResult,
    RulesClassifier,
)
from incident_intel.schemas import EventBundle, LogEvent, SupportTicket


class EvaluationCase(BaseModel):
    case_id: str
    expected_category: ClassificationCategory
    service: str
    message: str
    attributes: dict[str, str | int | float | bool | None]

    def to_bundle(self, index: int) -> EventBundle:
        observed_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC) + timedelta(minutes=index)
        return EventBundle(
            correlation_id=f"EVAL-{index:04d}",
            ticket=SupportTicket(
                ticket_id=f"EVAL-TICKET-{index:04d}",
                subject=f"Synthetic evaluation case {self.case_id}",
                description="Synthetic held-out support case used only for classifier evaluation.",
                priority="medium",
                source="monitoring",
                requester_role="Synthetic Operator",
                created_at=observed_at - timedelta(minutes=1),
                tags=("synthetic-evaluation",),
            ),
            logs=(
                LogEvent(
                    event_id=f"EVAL-EVENT-{index:04d}",
                    observed_at=observed_at,
                    service=self.service,
                    severity="warning",
                    message=self.message,
                    synthetic_user_id=f"eval-user-{index:04d}",
                    attributes=self.attributes,
                ),
            ),
        )


class EvaluationDataset(BaseModel):
    version: str
    description: str
    cases: tuple[EvaluationCase, ...]


class CategoryMetrics(BaseModel):
    support: int
    precision: float
    recall: float
    f1: float


class EvaluationReport(BaseModel):
    dataset_version: str
    provider: str
    model_version: str
    prompt_version: str
    run_timestamp: AwareDatetime
    case_count: int
    per_category: dict[str, CategoryMetrics]
    macro_f1: float
    abstention_rate: float
    unsupported_evidence_rate: float
    citation_validity: float
    median_latency_ms: float
    p95_latency_ms: float


def evaluate_dataset(dataset_path: Path) -> EvaluationReport:
    dataset = EvaluationDataset.model_validate_json(dataset_path.read_text(encoding="utf-8"))
    classifier = RulesClassifier()
    observations: list[tuple[EvaluationCase, EventBundle, ClassificationResult]] = []
    for index, case in enumerate(dataset.cases, start=1):
        bundle = case.to_bundle(index)
        observations.append((case, bundle, classifier.classify(bundle)))

    categories = sorted({case.expected_category for case in dataset.cases})
    per_category = {
        category: _category_metrics(category, observations) for category in categories
    }
    latencies = sorted(result.latency_ms for _case, _bundle, result in observations)
    citation_valid_count = sum(
        _citations_are_valid(bundle, result) for _case, bundle, result in observations
    )
    unsupported_count = sum(
        result.category != "uncategorized" and not _citations_are_valid(bundle, result)
        for _case, bundle, result in observations
    )
    abstention_count = sum(
        result.category == "uncategorized" for _case, _bundle, result in observations
    )
    case_count = len(observations)
    return EvaluationReport(
        dataset_version=dataset.version,
        provider=classifier.provider,
        model_version=classifier.model_version,
        prompt_version=classifier.prompt_version,
        run_timestamp=datetime.now(UTC),
        case_count=case_count,
        per_category=per_category,
        macro_f1=_rounded(sum(item.f1 for item in per_category.values()) / len(per_category)),
        abstention_rate=_rounded(abstention_count / case_count),
        unsupported_evidence_rate=_rounded(unsupported_count / case_count),
        citation_validity=_rounded(citation_valid_count / case_count),
        median_latency_ms=_rounded(median(latencies), digits=6),
        p95_latency_ms=_rounded(latencies[math.ceil(0.95 * case_count) - 1], digits=6),
    )


def _category_metrics(
    category: str,
    observations: list[tuple[EvaluationCase, EventBundle, ClassificationResult]],
) -> CategoryMetrics:
    true_positive = sum(
        case.expected_category == category and result.category == category
        for case, _bundle, result in observations
    )
    false_positive = sum(
        case.expected_category != category and result.category == category
        for case, _bundle, result in observations
    )
    false_negative = sum(
        case.expected_category == category and result.category != category
        for case, _bundle, result in observations
    )
    support = sum(case.expected_category == category for case, _bundle, _result in observations)
    precision = true_positive / (true_positive + false_positive) if true_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return CategoryMetrics(
        support=support,
        precision=_rounded(precision),
        recall=_rounded(recall),
        f1=_rounded(f1),
    )


def _citations_are_valid(bundle: EventBundle, result: ClassificationResult) -> bool:
    """Check citation-ID existence and nonempty predictions, not semantic entailment."""
    evidence_ids = {log.event_id for log in bundle.logs}
    citation_ids = set(result.cited_evidence_ids)
    if result.category != "uncategorized" and not citation_ids:
        return False
    return citation_ids.issubset(evidence_ids)


def _rounded(value: float, *, digits: int = 4) -> float:
    return round(value, digits)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the deterministic incident classifier.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = evaluate_dataset(args.dataset)
    rendered = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
