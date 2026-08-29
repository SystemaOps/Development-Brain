"""Command failure model (Phase 25).

Persists what failed in the worker so operations can be diagnosed and retried:
command id, attempt, failure category, message, correlation id, and retry
eligibility.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CommandFailureCategory(StrEnum):
    TRANSIENT_PROVIDER = "transient_provider"
    MODEL_FAILURE = "model_failure"
    EXECUTION_FAILURE = "execution_failure"
    VERIFICATION_FAILURE = "verification_failure"
    INVALID_INPUT = "invalid_input"
    INTERNAL = "internal"


class CommandFailure(BaseModel):
    """One recorded command-processing failure (Task 25.9)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    command_id: uuid.UUID
    command_type: str
    attempt: int = 1
    category: CommandFailureCategory = CommandFailureCategory.INTERNAL
    message: str = ""
    correlation_id: uuid.UUID | None = None
    retry_eligible: bool = True
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__ = ["CommandFailure", "CommandFailureCategory"]
