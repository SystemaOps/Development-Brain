"""Audit trail domain (Task 40.7).

Every meaningful system event is recorded: who/what triggered the command,
which model/executor ran, what base revision was used, what changed, what
evidence was collected, what verification decided, what observations were
published and which external tool was updated.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AuditAction(StrEnum):
    COMMAND_DISPATCHED = "command_dispatched"
    COMMAND_FAILED = "command_failed"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_BLOCKED = "execution_blocked"
    VERIFICATION_COMPLETED = "verification_completed"
    OBSERVATION_CREATED = "observation_created"
    OBSERVATION_PROJECTED = "observation_projected"
    OBSERVATION_PROJECTION_FAILED = "observation_projection_failed"
    PULL_REQUEST_CREATED = "pull_request_created"
    EXTERNAL_TOOL_UPDATED = "external_tool_updated"
    API_KEY_PROVISIONED = "api_key_provisioned"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    WEBHOOK_RECEIVED = "webhook_received"


class AuditEvent(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    action: AuditAction
    actor: str
    actor_role: str = ""
    project_id: uuid.UUID | None = None
    work_item_id: uuid.UUID | None = None
    execution_id: uuid.UUID | None = None
    repository_id: uuid.UUID | None = None
    details: dict[str, object] = Field(default_factory=dict)


__all__ = ["AuditAction", "AuditEvent"]
