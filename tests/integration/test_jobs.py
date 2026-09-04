from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select, text

from incident_intel.api import create_app
from incident_intel.classification import ClassificationResult, RulesClassifier
from incident_intel.config import Settings
from incident_intel.db import classifications, outbox_jobs
from incident_intel.postgres import (
    PostgresIncidentRepository,
    PostgresIngestionStore,
    PostgresJobRepository,
)
from incident_intel.schemas import EventBundle
from incident_intel.worker import run_once

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "auth_failure_bundle.json"


@pytest.fixture(autouse=True)
def empty_tables(database_engine: Engine) -> None:
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")
    with database_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE incidents, event_ingestions CASCADE"))


def seed_incident(engine: Engine):
    bundle = EventBundle.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    PostgresIngestionStore(engine).ingest("fixture-job-001", bundle)
    incident_id = PostgresIncidentRepository(engine).list_incidents().items[0].incident_id
    return incident_id


def test_job_claim_is_exclusive_and_increments_attempt(database_engine: Engine) -> None:
    repository = PostgresJobRepository(database_engine)
    job = repository.create_classification_job(seed_incident(database_engine))

    claimed = repository.claim_jobs(worker_id="worker-a", limit=1)
    second_claim = repository.claim_jobs(worker_id="worker-b", limit=1)

    assert job.state == "pending"
    assert len(claimed) == 1
    assert claimed[0].job_id == job.job_id
    assert claimed[0].state == "processing"
    assert claimed[0].attempt_count == 1
    assert claimed[0].claimed_by == "worker-a"
    assert second_claim == ()


def test_two_workers_cannot_claim_same_job(database_engine: Engine) -> None:
    repository = PostgresJobRepository(database_engine)
    repository.create_classification_job(seed_incident(database_engine))
    barrier = Barrier(2)

    def claim(worker_id: str):
        barrier.wait(timeout=5)
        return repository.claim_jobs(worker_id=worker_id, limit=1)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("worker-a", "worker-b")))

    claimed = [job for batch in results for job in batch]
    assert len(claimed) == 1
    assert claimed[0].attempt_count == 1


def test_retry_backoff_and_terminal_failure(database_engine: Engine) -> None:
    repository = PostgresJobRepository(database_engine)
    job = repository.create_classification_job(seed_incident(database_engine), max_attempts=2)
    now = datetime.now(UTC) + timedelta(seconds=1)
    repository.claim_jobs(worker_id="worker-a", limit=1, now=now)

    retry = repository.fail_job(job.job_id, "ProviderTimeout", retryable=True, now=now)

    assert retry.state == "retry_pending"
    assert retry.next_attempt_at == now + timedelta(seconds=10)
    assert repository.claim_jobs(
        worker_id="worker-b", limit=1, now=now + timedelta(seconds=9)
    ) == ()
    claimed_again = repository.claim_jobs(
        worker_id="worker-b", limit=1, now=now + timedelta(seconds=10)
    )
    assert claimed_again[0].attempt_count == 2

    failed = repository.fail_job(
        job.job_id,
        "ProviderTimeout",
        retryable=True,
        now=now + timedelta(seconds=10),
    )

    assert failed.state == "failed"
    assert failed.last_error_class == "ProviderTimeout"


def test_worker_persists_classification_and_completes_job(database_engine: Engine) -> None:
    incident_id = seed_incident(database_engine)
    repository = PostgresJobRepository(database_engine)
    job = repository.create_classification_job(incident_id)

    processed = run_once(
        jobs=repository,
        incidents=PostgresIncidentRepository(database_engine),
        classifier=RulesClassifier(),
        worker_id="worker-demo",
    )

    completed = repository.get_job(job.job_id)
    assert processed == 1
    assert completed is not None
    assert completed.state == "completed"
    assert completed.result_id is not None
    with database_engine.connect() as connection:
        stored = connection.execute(select(classifications)).mappings().one()
        pending_count = connection.execute(
            select(func.count()).select_from(outbox_jobs).where(outbox_jobs.c.state == "pending")
        ).scalar_one()
    assert stored["incident_id"] == incident_id
    assert stored["category"] == "authentication_failure"
    assert stored["cited_evidence_ids"] == ["LOG-2001", "LOG-2002"]
    assert pending_count == 0


def test_replayed_completion_does_not_duplicate_result(database_engine: Engine) -> None:
    repository = PostgresJobRepository(database_engine)
    job = repository.create_classification_job(seed_incident(database_engine))
    repository.claim_jobs(worker_id="worker-a", limit=1)
    result = ClassificationResult(
        provider="test",
        category="uncategorized",
        confidence=0.2,
        cited_evidence_ids=(),
        reason_codes=("test",),
        explanation="Synthetic replay proof.",
        model_version="test-v1",
        prompt_version="none",
        latency_ms=1,
    )

    first = repository.complete_classification(job.job_id, result)
    replayed = repository.complete_classification(job.job_id, result)

    with database_engine.connect() as connection:
        result_count = connection.execute(
            select(func.count()).select_from(classifications)
        ).scalar_one()
    assert replayed.result_id == first.result_id
    assert result_count == 1


@pytest.mark.anyio
async def test_job_api_creates_and_reads_classification_job(
    database_url: str,
    database_engine: Engine,
) -> None:
    incident_id = seed_incident(database_engine)
    app = create_app(settings=Settings(storage_backend="postgres", database_url=database_url))
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(f"/incidents/{incident_id}/classifications")
            job_id = created.json()["job_id"]
            retrieved = await client.get(f"/jobs/{job_id}")
            missing = await client.get(f"/jobs/{uuid4()}")

    assert created.status_code == 202
    assert created.json()["state"] == "pending"
    assert retrieved.status_code == 200
    assert retrieved.json() == created.json()
    assert missing.status_code == 404
    assert missing.json()["code"] == "job_not_found"
