from typing import Literal

from pydantic import BaseModel

from incident_intel.schemas import EventBundle

RiskLevel = Literal["low", "medium", "high"]


class AuthFailureEvidence(BaseModel):
    correlation_id: str
    ticket_id: str
    category: Literal["authentication_failure"]
    risk_level: RiskLevel
    affected_synthetic_users: tuple[str, ...]
    signals: tuple[str, ...]
    support_summary: str


def extract_auth_failure_evidence(bundle: EventBundle) -> AuthFailureEvidence:
    users = sorted({log.synthetic_user_id for log in bundle.logs})
    signals = _signals_for_bundle(bundle)

    return AuthFailureEvidence(
        correlation_id=bundle.correlation_id,
        ticket_id=bundle.ticket.ticket_id,
        category="authentication_failure",
        risk_level=_risk_level(signals),
        affected_synthetic_users=tuple(users),
        signals=tuple(signals),
        support_summary=_support_summary(users, signals, len(bundle.logs)),
    )


def _signals_for_bundle(bundle: EventBundle) -> list[str]:
    signals: list[str] = []
    failure_count = 0

    for log in bundle.logs:
        message = log.message.lower()
        attributes = log.attributes

        if attributes.get("result") == "denied" and "mfa" in str(attributes.get("auth_method", "")):
            signals.append("mfa_denied")

        if attributes.get("lockout") is True or "lockout" in message:
            signals.append("account_lockout")

        if isinstance(attributes.get("failure_count"), int):
            failure_count = max(failure_count, int(attributes["failure_count"]))

    if failure_count >= 3:
        signals.append("repeated_failures")

    return list(dict.fromkeys(signals))


def _risk_level(signals: list[str]) -> RiskLevel:
    if "account_lockout" in signals or "repeated_failures" in signals:
        return "high"
    if "mfa_denied" in signals:
        return "medium"
    return "low"


def _support_summary(users: list[str], signals: list[str], log_count: int) -> str:
    user_summary = ", ".join(users) if users else "unknown synthetic user"
    signal_summary = _humanize_signals(signals)
    return (
        f"Synthetic user {user_summary} hit {signal_summary} signals "
        f"across {log_count} identity-provider logs."
    )


def _humanize_signals(signals: list[str]) -> str:
    labels_by_signal = {
        "mfa_denied": "MFA denial",
        "account_lockout": "account lockout",
    }
    labels = [labels_by_signal[signal] for signal in signals if signal in labels_by_signal]
    if not labels:
        return "no authentication failure"
    if len(labels) == 1:
        return labels[0]
    return f"{' and '.join(labels[:-1])} and {labels[-1]}"
