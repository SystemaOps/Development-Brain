"""Retry classification for orchestrator nodes (Phase 28).

Distinguishes failure kinds so each has appropriate retry behavior
(Task 28.9): transient provider failures retry quickly, model failures retry
with backoff, execution/verification failures go through the retry loop,
human decisions pause, invalid inputs fail fast.
"""

from __future__ import annotations

from dataclasses import dataclass


class RetryKind:
    TRANSIENT_PROVIDER = "transient_provider"
    MODEL_FAILURE = "model_failure"
    EXECUTION_FAILURE = "execution_failure"
    VERIFICATION_FAILURE = "verification_failure"
    HUMAN_DECISION_REQUIRED = "human_decision_required"
    INVALID_INPUT = "invalid_input"


@dataclass
class RetryClassification:
    kind: str
    retryable: bool
    max_attempts: int = 3
    reason: str = ""


def classify_retry(exc: Exception) -> RetryClassification:
    """Map an exception to a retry classification."""
    message = f"{type(exc).__name__}: {exc}".lower()

    if _contains(message, ("invalid", "validation", "not found", "no executor")):
        return RetryClassification(RetryKind.INVALID_INPUT, retryable=False, max_attempts=1)
    if _contains(message, ("human", "approval", "clarification")):
        return RetryClassification(
            RetryKind.HUMAN_DECISION_REQUIRED, retryable=False, max_attempts=1
        )
    if _contains(message, ("verification", "verify")):
        return RetryClassification(RetryKind.VERIFICATION_FAILURE, retryable=True, max_attempts=3)
    if _contains(message, ("execution", "executor")):
        return RetryClassification(RetryKind.EXECUTION_FAILURE, retryable=True, max_attempts=3)
    if _contains(message, ("timeout", "unavailable", "connection", "transient", "retry")):
        return RetryClassification(RetryKind.TRANSIENT_PROVIDER, retryable=True, max_attempts=5)
    if _contains(message, ("model", "llm", "token", "context window")):
        return RetryClassification(RetryKind.MODEL_FAILURE, retryable=True, max_attempts=3)
    return RetryClassification(RetryKind.EXECUTION_FAILURE, retryable=True, max_attempts=3)


def _contains(message: str, needles: tuple[str, ...]) -> bool:
    return any(needle in message for needle in needles)


__all__ = ["RetryClassification", "RetryKind", "classify_retry"]
