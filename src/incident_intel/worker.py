from incident_intel.classification import Classifier
from incident_intel.incidents import IncidentDetail, IncidentRepository
from incident_intel.jobs import JobRepository, RetryableJobError
from incident_intel.observability import MetricsRegistry
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
        try:
            incident = incidents.get_incident(job.incident_id)
            if incident is None:
                raise ValueError("incident not found")
            result = classifier.classify(_bundle_from_detail(incident))
            jobs.complete_classification(job.job_id, result)
        except Exception as error:  # worker boundary must persist every failure
            failed_job = jobs.fail_job(
                job.job_id,
                type(error).__name__,
                retryable=isinstance(error, RetryableJobError),
            )
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
