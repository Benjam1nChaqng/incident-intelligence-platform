import json
import logging
import os
import signal
from threading import Event

from incident_intel.classification import Classifier, RulesClassifier
from incident_intel.config import Settings
from incident_intel.incidents import IncidentDetail, IncidentRepository
from incident_intel.ingestion import StorageUnavailable
from incident_intel.jobs import InvalidJobState, JobRepository, RetryableJobError
from incident_intel.observability import MetricsRegistry
from incident_intel.postgres import (
    PostgresIncidentRepository,
    PostgresJobRepository,
    create_engine_from_url,
)
from incident_intel.schemas import EventBundle, LogEvent, SupportTicket


def run_once(
    *,
    jobs: JobRepository,
    incidents: IncidentRepository,
    classifier: Classifier,
    worker_id: str,
    batch_size: int = 10,
    metrics: MetricsRegistry | None = None,
) -> int:
    claimed = jobs.claim_jobs(worker_id=worker_id, limit=batch_size)
    for job in claimed:
        claim_token = job.claim_token
        if claim_token is None:
            continue
        try:
            incident = incidents.get_incident(job.incident_id)
            if incident is None:
                raise ValueError("incident not found")
            result = classifier.classify(_bundle_from_detail(incident))
            jobs.complete_classification(
                job.job_id,
                result,
                claim_token=claim_token,
            )
        except InvalidJobState:
            continue
        except Exception as error:  # worker boundary must persist every failure
            try:
                failed_job = jobs.fail_job(
                    job.job_id,
                    type(error).__name__,
                    claim_token=claim_token,
                    retryable=isinstance(error, (RetryableJobError, StorageUnavailable)),
                )
            except InvalidJobState:
                continue
            if metrics is not None:
                metrics.increment("retried" if failed_job.state == "retry_pending" else "failed")
    return len(claimed)


def _bundle_from_detail(incident: IncidentDetail) -> EventBundle:
    return EventBundle(
        correlation_id=incident.correlation_id,
        ticket=SupportTicket(
            ticket_id=incident.ticket.ticket_id,
            subject=incident.ticket.subject,
            description=incident.ticket.description,
            priority=incident.ticket.priority,
            source=incident.ticket.source,
            requester_role=incident.ticket.requester_role,
            created_at=incident.ticket.created_at,
            tags=list(incident.ticket.tags),
        ),
        logs=[
            LogEvent(
                event_id=evidence.event_id,
                observed_at=evidence.observed_at,
                service=evidence.service,
                severity=evidence.severity,
                message=evidence.message,
                synthetic_user_id=evidence.synthetic_user_id,
                attributes=evidence.attributes,
            )
            for evidence in incident.evidence
        ],
    )


def run_forever(
    *,
    jobs: JobRepository,
    incidents: IncidentRepository,
    classifier: Classifier,
    worker_id: str,
    stop: Event,
    poll_interval_seconds: float = 1.0,
) -> None:
    if not 0.1 <= poll_interval_seconds <= 60:
        raise ValueError("poll interval must be between 0.1 and 60 seconds")
    metrics = MetricsRegistry()
    logger = logging.getLogger("incident_intel.worker")
    consecutive_failures = 0
    previous_counters = {"retried": 0, "failed": 0}
    while not stop.is_set():
        wait_seconds = 0.0
        try:
            processed = run_once(
                jobs=jobs,
                incidents=incidents,
                classifier=classifier,
                worker_id=worker_id,
                metrics=metrics,
            )
            consecutive_failures = 0
            if processed == 0:
                wait_seconds = poll_interval_seconds
        except Exception as error:  # keep the process alive across infrastructure outages
            consecutive_failures = min(7, consecutive_failures + 1)
            wait_seconds = min(
                60.0,
                max(1.0, poll_interval_seconds) * (2 ** (consecutive_failures - 1)),
            )
            logger.warning(
                json.dumps(
                    {
                        "event": "worker_poll_failed",
                        "error_class": "".join(
                            char
                            for char in type(error).__name__[:80]
                            if char.isascii() and (char.isalnum() or char == "_")
                        ),
                        "process_id": os.getpid(),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        counters = metrics.snapshot().counters
        worker_counters = {name: counters[name] for name in previous_counters}
        if worker_counters != previous_counters:
            logger.info(
                json.dumps(
                    {
                        "event": "worker_metrics",
                        "scope": "worker_process",
                        "process_id": os.getpid(),
                        "counters": worker_counters,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            previous_counters = worker_counters
        if wait_seconds:
            stop.wait(wait_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_env()
    if settings.storage_backend != "postgres" or settings.database_url is None:
        raise ValueError("worker requires PostgreSQL storage")
    worker_id = os.environ.get("INCIDENT_INTEL_WORKER_ID", "synthetic-worker-1")
    engine = create_engine_from_url(settings.database_url)
    stop = Event()

    def stop_worker(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGINT, stop_worker)
    signal.signal(signal.SIGTERM, stop_worker)
    try:
        run_forever(
            jobs=PostgresJobRepository(engine),
            incidents=PostgresIncidentRepository(engine),
            classifier=RulesClassifier(),
            worker_id=worker_id,
            stop=stop,
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
