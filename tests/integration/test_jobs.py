from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_urlsafe
from threading import Barrier
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select, text

from incident_intel.api import create_app
from incident_intel.auth import OperatorClaims, issue_token
from incident_intel.classification import ClassificationResult, RulesClassifier
from incident_intel.config import Settings
from incident_intel.db import classifications, outbox_jobs
from incident_intel.jobs import InvalidJobState
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
    assert claimed[0].claim_token is not None
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


def test_expired_worker_claim_is_recovered(database_engine: Engine) -> None:
    repository = PostgresJobRepository(database_engine)
    job = repository.create_classification_job(seed_incident(database_engine))
    first_claim_at = datetime.now(UTC) + timedelta(seconds=1)
    first_claim = repository.claim_jobs(
        worker_id="same-worker-name", limit=1, now=first_claim_at
    )[0]

    early = repository.claim_jobs(
        worker_id="same-worker-name",
        limit=1,
        now=first_claim_at + timedelta(minutes=4, seconds=59),
    )
    recovered = repository.claim_jobs(
        worker_id="same-worker-name",
        limit=1,
        now=first_claim_at + timedelta(minutes=5),
    )

    assert early == ()
    assert recovered[0].job_id == job.job_id
    assert recovered[0].attempt_count == 2
    assert recovered[0].claimed_by == "same-worker-name"
    assert recovered[0].claim_token != first_claim.claim_token
    with pytest.raises(InvalidJobState):
        repository.fail_job(
            job.job_id,
            "StaleWorkerError",
            claim_token=first_claim.claim_token,
            retryable=True,
            now=first_claim_at + timedelta(minutes=5),
        )
    bundle = EventBundle.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    with pytest.raises(InvalidJobState):
        repository.complete_classification(
            job.job_id, RulesClassifier().classify(bundle), claim_token=first_claim.claim_token
        )
    with database_engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(classifications)).scalar() == 0
    assert repository.get_job(job.job_id).claim_token == recovered[0].claim_token


def test_retry_backoff_and_terminal_failure(database_engine: Engine) -> None:
    repository = PostgresJobRepository(database_engine)
    job = repository.create_classification_job(seed_incident(database_engine), max_attempts=2)
    now = datetime.now(UTC) + timedelta(seconds=1)
    first_claim = repository.claim_jobs(worker_id="worker-a", limit=1, now=now)[0]

    retry = repository.fail_job(
        job.job_id,
        "ProviderTimeout",
        claim_token=first_claim.claim_token,
        retryable=True,
        now=now,
    )

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
        claim_token=claimed_again[0].claim_token,
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
    claimed = repository.claim_jobs(worker_id="worker-a", limit=1)[0]
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

    first = repository.complete_classification(
        job.job_id,
        result,
        claim_token=claimed.claim_token,
    )
    replayed = repository.complete_classification(
        job.job_id,
        result,
        claim_token=claimed.claim_token,
    )

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
    secret = token_urlsafe(32)
    app = create_app(
        settings=Settings(
            storage_backend="postgres",
            database_url=database_url,
            token_secret=secret,
        )
    )
    viewer_token = issue_token(
        OperatorClaims(operator_id="synthetic-viewer-1", role="viewer"),
        secret=secret,
    )
    operator_token = issue_token(
        OperatorClaims(operator_id="synthetic-operator-1", role="operator"),
        secret=secret,
    )
    viewer = {"Authorization": f"Bearer {viewer_token}"}
    operator = {"Authorization": f"Bearer {operator_token}"}
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            forbidden = await client.post(
                f"/incidents/{incident_id}/classifications", headers=viewer
            )
            created = await client.post(
                f"/incidents/{incident_id}/classifications", headers=operator
            )
            job_id = created.json()["job_id"]
            retrieved = await client.get(f"/jobs/{job_id}", headers=viewer)
            missing = await client.get(f"/jobs/{uuid4()}", headers=viewer)
            run_once(
                jobs=PostgresJobRepository(database_engine),
                incidents=PostgresIncidentRepository(database_engine),
                classifier=RulesClassifier(),
                worker_id="synthetic-api-proof",
            )
            completed = await client.get(f"/jobs/{job_id}", headers=viewer)
            result_id = completed.json()["result_id"]
            result = await client.get(f"/classifications/{result_id}", headers=viewer)
            missing_result = await client.get(f"/classifications/{uuid4()}", headers=viewer)

    assert forbidden.status_code == 403
    assert created.status_code == 202
    assert created.json()["state"] == "pending"
    assert retrieved.status_code == 200
    assert retrieved.json() == created.json()
    assert missing.status_code == 404
    assert missing.json()["code"] == "job_not_found"
    assert "claim_token" not in retrieved.json()
    assert completed.json()["state"] == "completed"
    assert result.status_code == 200
    assert result.json()["classification_id"] == result_id
    assert result.json()["incident_id"] == str(incident_id)
    assert result.json()["category"] == "authentication_failure"
    assert result.json()["cited_evidence_ids"] == ["LOG-2001", "LOG-2002"]
    assert missing_result.status_code == 404
    assert missing_result.json()["code"] == "classification_not_found"


@pytest.mark.anyio
async def test_admin_retry_preserves_attempt_history_and_only_grants_one_more_attempt(
    database_url: str, database_engine: Engine
) -> None:
    repository = PostgresJobRepository(database_engine)
    job = repository.create_classification_job(seed_incident(database_engine), max_attempts=1)
    claim = repository.claim_jobs(worker_id="synthetic-retry-proof")[0]
    repository.fail_job(
        job.job_id, "SyntheticFailure", claim_token=claim.claim_token, retryable=True
    )
    secret = token_urlsafe(32)
    app = create_app(settings=Settings(
        storage_backend="postgres", database_url=database_url, token_secret=secret
    ))

    def headers(role: str) -> dict[str, str]:
        token = issue_token(
            OperatorClaims(operator_id=f"synthetic-{role}-proof", role=role), secret=secret
        )
        return {"Authorization": f"Bearer {token}"}

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            path = f"/jobs/{job.job_id}/retry"
            assert (await client.post(path, headers=headers("operator"))).status_code == 403
            accepted = await client.post(path, headers=headers("admin"))
            assert accepted.status_code == 202
            assert accepted.json()["state"] == "retry_pending"
            assert accepted.json()["attempt_count"] == 1
            assert accepted.json()["max_attempts"] == 2
            assert accepted.json()["last_error_class"] == "SyntheticFailure"
            assert (await client.post(path, headers=headers("admin"))).status_code == 409
            missing = await client.post(f"/jobs/{uuid4()}/retry", headers=headers("admin"))
            assert missing.status_code == 404
            run_once(
                jobs=repository, incidents=PostgresIncidentRepository(database_engine),
                classifier=RulesClassifier(), worker_id="synthetic-retry-proof"
            )
            assert repository.get_job(job.job_id).attempt_count == 2
            assert repository.get_job(job.job_id).state == "completed"
            assert (await client.post(path, headers=headers("admin"))).status_code == 409
