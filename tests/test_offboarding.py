import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from incident_intel.ingestion import bundle_payload_hash
from incident_intel.offboarding import adapt_offboarding_fixture

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "google_workspace_offboarding.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_adapter_links_disabled_identity_access_and_endpoint_without_mutating_input() -> None:
    payload = load_fixture()
    original = copy.deepcopy(payload)

    bundle = adapt_offboarding_fixture(payload)

    assert payload == original
    assert bundle.correlation_id == "INC-OFFBOARD-001"
    assert bundle.ticket.ticket_id == "TCK-OFFBOARD-001"
    assert bundle.ticket.created_at == datetime(2026, 9, 4, 10, 6, tzinfo=UTC)
    assert len(bundle.logs) == 2
    disabled, access = bundle.logs
    assert [log.event_id for log in bundle.logs] == ["GW-DISABLED-001", "GW-ACCESS-001"]
    assert disabled.observed_at == datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    assert access.observed_at == datetime(2026, 9, 4, 10, 5, tzinfo=UTC)
    assert (
        disabled.synthetic_user_id == access.synthetic_user_id == "synthetic-user-offboarding-001"
    )
    assert disabled.attributes == {
        "event_type": "identity_disabled",
        "identity_state": "disabled",
        "synthetic_endpoint_id": "synthetic-endpoint-001",
        "fixture_only": True,
    }
    assert access.attributes == {
        "event_type": "access_attempt",
        "result": "allowed",
        "disabled_event_id": "GW-DISABLED-001",
        "synthetic_endpoint_id": "synthetic-endpoint-001",
        "fixture_only": True,
    }
    assert access.severity == "error"
    assert {log.service for log in bundle.logs} == {"synthetic-google-workspace"}
    assert adapt_offboarding_fixture(payload).model_dump_json() == bundle.model_dump_json()


def test_adapter_collapses_exact_duplicates_before_event_bundle_validation() -> None:
    payload = load_fixture()
    payload["access_events"].append(copy.deepcopy(payload["access_events"][0]))

    bundle = adapt_offboarding_fixture(payload)

    assert [log.event_id for log in bundle.logs] == ["GW-DISABLED-001", "GW-ACCESS-001"]
    assert bundle_payload_hash(bundle) == bundle_payload_hash(
        adapt_offboarding_fixture(load_fixture())
    )


def test_adapter_rejects_conflicting_duplicate_event_ids() -> None:
    payload = load_fixture()
    duplicate = copy.deepcopy(payload["access_events"][0])
    duplicate["result"] = "denied"
    payload["access_events"].append(duplicate)

    with pytest.raises(ValueError, match="conflicting duplicate event_id"):
        adapt_offboarding_fixture(payload)


def test_adapter_rejects_access_id_colliding_with_disablement_id() -> None:
    payload = load_fixture()
    payload["access_events"][0]["event_id"] = "GW-DISABLED-001"

    with pytest.raises(ValueError, match="event_id"):
        adapt_offboarding_fixture(payload)


@pytest.mark.parametrize("location", ["identity", "access", "endpoint"])
def test_adapter_rejects_missing_identity_without_inventing_a_link(location: str) -> None:
    payload = load_fixture()
    if location == "identity":
        del payload["identity"]
    elif location == "access":
        del payload["access_events"][0]["synthetic_user_id"]
    else:
        del payload["endpoint"]["assigned_synthetic_user_id"]

    with pytest.raises(ValidationError):
        adapt_offboarding_fixture(payload)


@pytest.mark.parametrize("location", ["endpoint_owner", "access_user", "access_endpoint"])
def test_adapter_rejects_unrelated_identity_or_endpoint(location: str) -> None:
    payload = load_fixture()
    if location == "endpoint_owner":
        payload["endpoint"]["assigned_synthetic_user_id"] = "synthetic-user-unrelated"
    elif location == "access_user":
        payload["access_events"][0]["synthetic_user_id"] = "synthetic-user-unrelated"
    else:
        payload["access_events"][0]["synthetic_endpoint_id"] = "synthetic-endpoint-unrelated"

    with pytest.raises(ValueError, match="link"):
        adapt_offboarding_fixture(payload)


@pytest.mark.parametrize("observed_at", ["2026-09-04T09:59:00Z", "2026-09-04T10:00:00Z"])
def test_adapter_requires_access_strictly_after_disablement(observed_at: str) -> None:
    payload = load_fixture()
    payload["access_events"][0]["observed_at"] = observed_at

    with pytest.raises(ValueError, match="after disablement"):
        adapt_offboarding_fixture(payload)


@pytest.mark.parametrize("field", ["disabled_at", "observed_at"])
def test_adapter_rejects_ambiguous_naive_timestamps(field: str) -> None:
    payload = load_fixture()
    target = payload["identity"] if field == "disabled_at" else payload["access_events"][0]
    target[field] = "2026-09-04T10:05:00"

    with pytest.raises(ValidationError):
        adapt_offboarding_fixture(payload)


@pytest.mark.parametrize("user_id", ["", "person@example.invalid", "user-without-synthetic-prefix"])
def test_adapter_requires_explicit_synthetic_identity_ids(user_id: str) -> None:
    payload = load_fixture()
    payload["identity"]["synthetic_user_id"] = user_id

    with pytest.raises(ValidationError):
        adapt_offboarding_fixture(payload)


@pytest.mark.parametrize("field, value", [("state", "active"), ("disabled_at", None)])
def test_adapter_requires_a_disabled_identity(field: str, value: object) -> None:
    payload = load_fixture()
    payload["identity"][field] = value

    with pytest.raises(ValidationError):
        adapt_offboarding_fixture(payload)


def test_adapter_requires_at_least_one_access_event() -> None:
    payload = load_fixture()
    payload["access_events"] = []

    with pytest.raises(ValidationError):
        adapt_offboarding_fixture(payload)


def test_adapter_preserves_denied_access_without_relabeling_it_as_allowed() -> None:
    payload = load_fixture()
    payload["access_events"][0]["result"] = "denied"

    access = adapt_offboarding_fixture(payload).logs[1]

    assert access.attributes["result"] == "denied"
    assert access.severity == "warning"


def test_adapter_orders_access_events_by_time_then_id_for_stable_ingestion_hashes() -> None:
    payload = load_fixture()
    payload["access_events"].extend(
        [
            dict(payload["access_events"][0], event_id="GW-ACCESS-003"),
            dict(
                payload["access_events"][0],
                event_id="GW-ACCESS-002",
                observed_at="2026-09-04T10:04:00Z",
            ),
        ]
    )
    reversed_payload = copy.deepcopy(payload)
    reversed_payload["access_events"].reverse()

    bundle = adapt_offboarding_fixture(payload)

    assert [log.event_id for log in bundle.logs] == [
        "GW-DISABLED-001",
        "GW-ACCESS-002",
        "GW-ACCESS-001",
        "GW-ACCESS-003",
    ]
    assert bundle_payload_hash(bundle) == bundle_payload_hash(
        adapt_offboarding_fixture(reversed_payload)
    )


def test_adapter_normalizes_equivalent_timestamp_offsets_for_replay() -> None:
    payload = load_fixture()
    payload["identity"]["disabled_at"] = "2026-09-04T03:00:00-07:00"
    payload["access_events"][0]["observed_at"] = "2026-09-04T03:05:00-07:00"
    payload["ticket"]["created_at"] = "2026-09-04T03:06:00-07:00"

    assert bundle_payload_hash(adapt_offboarding_fixture(payload)) == bundle_payload_hash(
        adapt_offboarding_fixture(load_fixture())
    )


@pytest.mark.anyio
async def test_adapted_fixture_ingests_and_replays_through_existing_events_route(app) -> None:
    bundle = adapt_offboarding_fixture(load_fixture())
    repeated_payload = load_fixture()
    repeated_payload["access_events"] *= 2
    replay = adapt_offboarding_fixture(repeated_payload)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/events",
            headers={"Idempotency-Key": "synthetic-offboarding-001"},
            json=bundle.model_dump(mode="json"),
        )
        second = await client.post(
            "/events",
            headers={"Idempotency-Key": "synthetic-offboarding-001"},
            json=replay.model_dump(mode="json"),
        )

    assert first.status_code == 201
    assert first.json() == {
        "correlation_id": "INC-OFFBOARD-001",
        "idempotency_key": "synthetic-offboarding-001",
        "status": "accepted",
        "duplicate": False,
        "ticket_id": "TCK-OFFBOARD-001",
        "log_count": 2,
    }
    assert second.status_code == 200
    assert second.json() == dict(first.json(), status="duplicate", duplicate=True)
