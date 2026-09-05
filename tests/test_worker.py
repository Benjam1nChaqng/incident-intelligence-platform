import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from incident_intel.classification import RulesClassifier
from incident_intel.incidents import EvidenceDetail, IncidentDetail, TicketDetail
from incident_intel.ingestion import StorageUnavailable
from incident_intel.jobs import InvalidJobState, JobRecord, RetryableJobError, retry_delay
from incident_intel.observability import MetricsRegistry
from incident_intel.schemas import EventBundle
from incident_intel.worker import run_forever, run_once


@pytest.fixture
def job() -> JobRecord:
    now = datetime(2026, 9, 4, tzinfo=UTC)
    return JobRecord(
        job_id=uuid4(),
        incident_id=uuid4(),
        job_type="classify_incident",
        state="processing",
        attempt_count=1,
        max_attempts=3,
        next_attempt_at=now,
        claimed_at=now,
        claimed_by="test-worker",
        claim_token=uuid4(),
        completed_at=None,
        result_id=None,
        last_error_class=None,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def incident(job: JobRecord) -> IncidentDetail:
    bundle = EventBundle.model_validate_json(
        (Path(__file__).parent / "fixtures" / "auth_failure_bundle.json").read_text()
    )
    return IncidentDetail(
        incident_id=job.incident_id,
        correlation_id=bundle.correlation_id,
        status="open",
        priority=bundle.ticket.priority,
        summary=bundle.ticket.subject,
        created_at=job.created_at,
        updated_at=job.updated_at,
        ticket=TicketDetail(**bundle.ticket.model_dump()),
        evidence=tuple(EvidenceDetail(**event.model_dump()) for event in bundle.logs),
    )


def stop_after_polls(count: int) -> Mock:
    stop = Mock()
    stop.is_set.side_effect = [False] * count + [True]
    return stop


def test_claim_outage_recovers_and_backoff_resets(job, incident, caplog) -> None:
    jobs = Mock()
    jobs.claim_jobs.side_effect = [
        StorageUnavailable("private connection"),
        (job,),
        StorageUnavailable("private connection"),
        (),
    ]
    stop = stop_after_polls(4)
    incidents = Mock()
    incidents.get_incident.return_value = incident

    with caplog.at_level(logging.INFO, logger="incident_intel.worker"):
        run_forever(
            jobs=jobs,
            incidents=incidents,
            classifier=RulesClassifier(),
            worker_id="test-worker",
            stop=stop,
            poll_interval_seconds=0.25,
        )

    assert jobs.claim_jobs.call_count == 4
    jobs.complete_classification.assert_called_once()
    assert [call.args[0] for call in stop.wait.call_args_list] == [1.0, 1.0, 0.25]
    assert "private connection" not in caplog.text
    assert all(
        json.loads(record.message)["error_class"] == "StorageUnavailable"
        for record in caplog.records
    )


def test_stale_completion_abandons_attempt_without_failure(job, incident) -> None:
    jobs = Mock()
    jobs.claim_jobs.return_value = (job,)
    jobs.complete_classification.side_effect = InvalidJobState
    incidents = Mock()
    incidents.get_incident.return_value = incident

    assert (
        run_once(
            jobs=jobs, incidents=incidents, classifier=RulesClassifier(), worker_id="test-worker"
        )
        == 1
    )

    assert jobs.complete_classification.call_args.kwargs["claim_token"] == job.claim_token
    jobs.fail_job.assert_not_called()


def test_retrieval_outage_schedules_retry_with_claim_token(job) -> None:
    jobs = Mock()
    jobs.claim_jobs.return_value = (job,)
    jobs.fail_job.return_value = job.model_copy(update={"state": "retry_pending"})
    incidents = Mock()
    incidents.get_incident.side_effect = StorageUnavailable("private incident content")
    classifier = Mock()
    metrics = MetricsRegistry()

    run_once(
        jobs=jobs,
        incidents=incidents,
        classifier=classifier,
        worker_id="test-worker",
        metrics=metrics,
    )

    jobs.fail_job.assert_called_once_with(
        job.job_id, "StorageUnavailable", claim_token=job.claim_token, retryable=True
    )
    classifier.classify.assert_not_called()
    assert metrics.snapshot().counters["retried"] == 1


def test_failure_persistence_outage_does_not_kill_polling(job, incident, caplog) -> None:
    jobs = Mock()
    jobs.claim_jobs.side_effect = [(job,), ()]
    jobs.fail_job.side_effect = StorageUnavailable("private connection")
    incidents = Mock()
    incidents.get_incident.return_value = incident
    classifier = Mock()
    classifier.classify.side_effect = RetryableJobError("private payload")
    stop = stop_after_polls(2)

    with caplog.at_level(logging.INFO, logger="incident_intel.worker"):
        run_forever(
            jobs=jobs,
            incidents=incidents,
            classifier=classifier,
            worker_id="test-worker",
            stop=stop,
        )

    assert jobs.claim_jobs.call_count == 2
    assert stop.wait.call_count == 2
    assert "private" not in caplog.text
    assert json.loads(caplog.records[0].message)["error_class"] == "StorageUnavailable"


def test_worker_emits_process_local_retry_and_failure_counters(job, caplog) -> None:
    jobs = Mock()
    jobs.claim_jobs.side_effect = [(job,), (job,), ()]
    jobs.fail_job.side_effect = [
        job.model_copy(update={"state": "retry_pending"}),
        job.model_copy(update={"state": "failed"}),
    ]
    incidents = Mock()
    incidents.get_incident.side_effect = StorageUnavailable("private payload")
    stop = stop_after_polls(3)

    with caplog.at_level(logging.INFO, logger="incident_intel.worker"):
        run_forever(
            jobs=jobs, incidents=incidents, classifier=Mock(), worker_id="test-worker", stop=stop
        )

    events = [json.loads(record.message) for record in caplog.records]
    assert [event["counters"] for event in events] == [
        {"retried": 1, "failed": 0},
        {"retried": 1, "failed": 1},
    ]
    assert all(event["event"] == "worker_metrics" for event in events)
    assert all(event["scope"] == "worker_process" for event in events)
    assert "private" not in caplog.text


def test_poll_backoff_is_bounded_without_busy_retry() -> None:
    jobs = Mock()
    jobs.claim_jobs.side_effect = StorageUnavailable
    stop = stop_after_polls(10)

    run_forever(jobs=jobs, incidents=Mock(), classifier=Mock(), worker_id="test-worker", stop=stop)

    assert [call.args[0] for call in stop.wait.call_args_list] == [
        1,
        2,
        4,
        8,
        16,
        32,
        60,
        60,
        60,
        60,
    ]


def test_retry_delay_caps_before_large_exponent() -> None:
    assert retry_delay(1).total_seconds() == 10
    assert retry_delay(6).total_seconds() == 300
    assert retry_delay(1_000_000).total_seconds() == 300
