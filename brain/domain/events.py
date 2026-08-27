"""Canonical event model.

External systems (Jira, OpenProject, XWiki, ...) are normalized into these
canonical events so downstream logic never cares which provider emitted them.
``correlation_id`` ties an operational chain together; ``causation_id`` says
which event caused the current one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import ProjectId


class EventType(StrEnum):
    PROJECT_CREATED = "project_created"
    REPOSITORY_REGISTERED = "repository_registered"
    REPOSITORY_REVISION_CHANGED = "repository_revision_changed"
    DOCUMENT_CHANGED = "document_changed"
    WORK_ITEM_CREATED = "work_item_created"
    WORK_ITEM_CHANGED = "work_item_changed"
    WORK_ITEM_ASSIGNED = "work_item_assigned"
    REQUIREMENT_CHANGED = "requirement_changed"

    EXECUTION_REQUESTED = "execution_requested"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"

    VERIFICATION_REQUESTED = "verification_requested"
    VERIFICATION_COMPLETED = "verification_completed"

    PULL_REQUEST_REQUESTED = "pull_request_requested"
    PULL_REQUEST_CREATED = "pull_request_created"

    HUMAN_FEEDBACK_RECEIVED = "human_feedback_received"
    KNOWLEDGE_CONFLICT_DETECTED = "knowledge_conflict_detected"
    OBSERVATION_CREATED = "observation_created"
    OBSERVATION_ACKNOWLEDGED = "observation_acknowledged"
    OBSERVATION_RESOLVED = "observation_resolved"


class EventEnvelope(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: EventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    project_id: ProjectId | None = None
    correlation_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    causation_id: uuid.UUID | None = None
    source: str
    idempotency_key: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
