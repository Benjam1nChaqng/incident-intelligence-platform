from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe

import pytest

from incident_intel.auth import (
    InvalidToken,
    OperatorClaims,
    authorize,
    issue_token,
    verify_token,
)


def test_signed_token_round_trip_and_role_authorization() -> None:
    secret = token_urlsafe(32)
    now = datetime.now(UTC)
    token = issue_token(
        OperatorClaims(operator_id="synthetic-operator-1", role="operator"),
        secret=secret,
        now=now,
        ttl=timedelta(minutes=5),
    )

    claims = verify_token(token, secret=secret, now=now + timedelta(seconds=1))

    assert claims.operator_id == "synthetic-operator-1"
    assert claims.role == "operator"
    assert authorize(claims, minimum_role="viewer") is True
    assert authorize(claims, minimum_role="admin") is False


@pytest.mark.parametrize("mutation", ["tamper", "expired"])
def test_token_rejects_tampering_and_expiration(mutation: str) -> None:
    secret = token_urlsafe(32)
    now = datetime.now(UTC)
    token = issue_token(
        OperatorClaims(operator_id="synthetic-viewer-1", role="viewer"),
        secret=secret,
        now=now,
        ttl=timedelta(seconds=2),
    )

    if mutation == "tamper":
        token = f"{token[:-1]}{'A' if token[-1] != 'A' else 'B'}"
        checked_at = now
    else:
        checked_at = now + timedelta(seconds=3)

    with pytest.raises(InvalidToken):
        verify_token(token, secret=secret, now=checked_at)
