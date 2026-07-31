from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain.enums import RetryCategory


@dataclass(frozen=True)
class RetryDecision:
    category: RetryCategory
    retryable: bool
    reason: str


def classify_exception(exc: BaseException) -> RetryDecision:
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()

    if isinstance(exc, PermissionError):
        return RetryDecision(RetryCategory.POLICY_DENIED, False, "Permission denied")

    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return RetryDecision(RetryCategory.INVALID_INPUT, False, "Invalid input")

    if isinstance(exc, TimeoutError) or "timeout" in name or "timed out" in text:
        return RetryDecision(RetryCategory.TRANSIENT_NETWORK, True, "Operation timed out")

    if isinstance(exc, ConnectionError) or "connection" in name or "connection" in text:
        return RetryDecision(
            RetryCategory.DEPENDENCY_UNAVAILABLE,
            True,
            "Dependency connection failed",
        )

    if (
        "server error" in text
        or "service unavailable" in text
        or any(status in text for status in ("500", "502", "503", "504"))
    ):
        return RetryDecision(
            RetryCategory.DEPENDENCY_UNAVAILABLE,
            True,
            "Dependency returned a retryable server error",
        )

    if "rate" in text or "capacity" in text or "429" in text:
        return RetryDecision(
            RetryCategory.RATE_OR_CAPACITY,
            True,
            "Provider rate or capacity limit",
        )

    if "concurrency" in text or "conflict" in text or "409" in text:
        return RetryDecision(
            RetryCategory.OPTIMISTIC_CONCURRENCY_CONFLICT,
            True,
            "Optimistic concurrency conflict",
        )

    if "authentication" in text or "unauthorized" in text or "401" in text:
        return RetryDecision(
            RetryCategory.AUTHENTICATION_FAILURE,
            False,
            "Authentication failed",
        )

    return RetryDecision(RetryCategory.UNKNOWN, False, "Unknown failure")


def calculate_retry_delay_seconds(
    attempt_count: int,
    *,
    base_seconds: int,
    max_seconds: int,
) -> int:
    exponent = max(attempt_count - 1, 0)
    return min(max_seconds, base_seconds * (2**exponent))
