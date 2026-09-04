import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, ValidationError

OperatorRole = Literal["viewer", "operator", "admin"]
ROLE_LEVEL: dict[OperatorRole, int] = {"viewer": 1, "operator": 2, "admin": 3}


class InvalidToken(Exception):  # noqa: N818 - stable domain name used by the API contract
    """Raised when an operator token cannot be trusted."""


class OperatorClaims(BaseModel):
    operator_id: str = Field(pattern=r"^synthetic-[a-z0-9-]{3,64}$")
    role: OperatorRole


class _TokenPayload(OperatorClaims):
    expires_at: AwareDatetime


def issue_token(
    claims: OperatorClaims,
    *,
    secret: str,
    now: datetime | None = None,
    ttl: timedelta = timedelta(minutes=15),
) -> str:
    _validate_secret(secret)
    if ttl <= timedelta(0) or ttl > timedelta(hours=1):
        raise ValueError("token ttl must be between 1 second and 1 hour")
    issued_at = now or datetime.now(UTC)
    if issued_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    payload = _TokenPayload(
        **claims.model_dump(),
        expires_at=issued_at + ttl,
    ).model_dump(mode="json")
    encoded_payload = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    signature = hmac.new(secret.encode(), encoded_payload.encode(), hashlib.sha256).digest()
    return f"{encoded_payload}.{_encode_bytes(signature)}"


def verify_token(
    token: str,
    *,
    secret: str,
    now: datetime | None = None,
) -> OperatorClaims:
    _validate_secret(secret)
    try:
        encoded_payload, encoded_signature = token.split(".", maxsplit=1)
        expected = hmac.new(secret.encode(), encoded_payload.encode(), hashlib.sha256).digest()
        actual = _decode_bytes(encoded_signature)
        if not hmac.compare_digest(actual, expected):
            raise InvalidToken
        payload = _TokenPayload.model_validate_json(_decode(encoded_payload))
    except (ValueError, UnicodeDecodeError, ValidationError, json.JSONDecodeError):
        raise InvalidToken from None
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at >= payload.expires_at:
        raise InvalidToken
    return OperatorClaims(operator_id=payload.operator_id, role=payload.role)


def authorize(claims: OperatorClaims, *, minimum_role: OperatorRole) -> bool:
    return ROLE_LEVEL[claims.role] >= ROLE_LEVEL[minimum_role]


def _validate_secret(secret: str) -> None:
    if len(secret) < 32:
        raise ValueError("token secret must contain at least 32 characters")


def _encode(value: str) -> str:
    return _encode_bytes(value.encode())


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> str:
    return _decode_bytes(value).decode("utf-8")


def _decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)
