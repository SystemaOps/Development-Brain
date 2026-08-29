"""Typed canonical event payloads.

External systems are normalized into ``EventEnvelope``s carrying one of these
typed payloads, so downstream handlers see well-typed data instead of raw
dicts.  Each payload serializes to the envelope's JSON ``payload`` field and
round-trips through ``model_dump(mode="json")`` / ``model_validate``, which is
also what makes envelopes storable in PostgreSQL ``jsonb`` columns.

Idempotency and correlation helpers live at the bottom of this module
(:func:`model_to_envelope`, :func:`event_to_model`, :func:`derive_event`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field, ValidationError

from brain.domain.documents import Document
from brain.domain.events import EventEnvelope, EventType
from brain.domain.executions import Execution, ExecutionResult
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import (
    ActorId,
    ExecutionId,
    ProjectId,
    RepositoryId,
    WorkItemId,
)
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.requirements import Requirement
from brain.domain.verification import VerificationResult
from brain.domain.work_items import WorkItem


class FeedbackVerdict(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"
    NOTE = "note"


class CanonicalEvent(BaseModel):
    """Base class for typed canonical event payloads."""

    event_type: ClassVar[EventType]

    def to_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class ProjectCreated(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.PROJECT_CREATED
    project: Project


class RepositoryRegistered(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.REPOSITORY_REGISTERED
    repository: Repository


class RepositoryRevisionChanged(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.REPOSITORY_REVISION_CHANGED
    repository_id: RepositoryId
    old_revision: str | None = None
    new_revision: str


class DocumentChanged(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.DOCUMENT_CHANGED
    document: Document


class WorkItemCreated(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.WORK_ITEM_CREATED
    work_item: WorkItem


class WorkItemChanged(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.WORK_ITEM_CHANGED
    work_item: WorkItem


class WorkItemAssigned(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.WORK_ITEM_ASSIGNED
    work_item_id: WorkItemId
    actor_id: ActorId
    assigned_by: ActorId | None = None
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RequirementChanged(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.REQUIREMENT_CHANGED
    requirement: Requirement


class ExecutionRequested(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.EXECUTION_REQUESTED
    execution: Execution


class ExecutionStarted(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.EXECUTION_STARTED
    execution: Execution


class ExecutionCompleted(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.EXECUTION_COMPLETED
    execution: Execution
    result: ExecutionResult | None = None


class VerificationRequested(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.VERIFICATION_REQUESTED
    execution_id: ExecutionId
    work_item_id: WorkItemId


class VerificationCompleted(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.VERIFICATION_COMPLETED
    verification: VerificationResult


class PullRequestRequested(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.PULL_REQUEST_REQUESTED
    project_id: ProjectId
    work_item_id: WorkItemId
    repository_id: RepositoryId
    base_revision: str
    head_revision: str


class PullRequestCreated(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.PULL_REQUEST_CREATED
    project_id: ProjectId
    work_item_id: WorkItemId
    external_ref: ExternalReference


class PullRequestMerged(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.PULL_REQUEST_MERGED
    external_ref: ExternalReference
    repository_id: RepositoryId | None = None


class HumanFeedbackReceived(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.HUMAN_FEEDBACK_RECEIVED
    work_item_id: WorkItemId
    actor_id: ActorId
    verdict: FeedbackVerdict
    feedback: str = ""


class KnowledgeConflictDetected(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.KNOWLEDGE_CONFLICT_DETECTED
    entity_id: uuid.UUID
    entity_type: str
    claim_a: str
    claim_b: str
    source_a: str
    source_b: str


class ObservationCreated(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.OBSERVATION_CREATED
    observation_id: uuid.UUID
    project_id: ProjectId
    observation_type: str
    title: str
    body: str = ""


class ObservationAcknowledged(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.OBSERVATION_ACKNOWLEDGED
    observation_id: uuid.UUID
    project_id: ProjectId


class ObservationResolved(CanonicalEvent):
    event_type: ClassVar[EventType] = EventType.OBSERVATION_RESOLVED
    observation_id: uuid.UUID
    project_id: ProjectId


EVENT_TYPE_TO_MODEL: dict[EventType, type[CanonicalEvent]] = {
    cls.event_type: cls for cls in CanonicalEvent.__subclasses__()
}


def model_to_envelope(
    event: CanonicalEvent,
    *,
    source: str,
    project_id: ProjectId | None = None,
    correlation_id: uuid.UUID | None = None,
    causation_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> EventEnvelope:
    """Wrap a typed canonical event in a transport-ready envelope."""
    return EventEnvelope(
        event_type=event.event_type,
        project_id=project_id,
        correlation_id=correlation_id or uuid.uuid4(),
        causation_id=causation_id,
        source=source,
        idempotency_key=idempotency_key,
        payload=event.to_payload(),
    )


def event_to_model(envelope: EventEnvelope) -> CanonicalEvent | None:
    """Reconstruct the typed canonical payload from an envelope, if known.

    Returns ``None`` for unknown event types and for envelopes whose payload
    does not match the expected shape (defensive: a malformed external event
    must not poison the processing chain).
    """
    model = EVENT_TYPE_TO_MODEL.get(envelope.event_type)
    if model is None:
        return None
    try:
        return model.model_validate(envelope.payload)
    except ValidationError:
        return None


def derive_event(
    parent: EventEnvelope,
    event: CanonicalEvent,
    *,
    source: str | None = None,
    idempotency_key: str | None = None,
) -> EventEnvelope:
    """Derive a child event that inherits the parent's correlation chain.

    ``correlation_id`` is carried from ``parent`` (one chain for webhook ->
    ingestion -> context -> execution -> verification); ``causation_id`` points
    back at the parent's ``event_id``.
    """
    return model_to_envelope(
        event,
        source=source or parent.source,
        project_id=parent.project_id,
        correlation_id=parent.correlation_id,
        causation_id=parent.event_id,
        idempotency_key=idempotency_key,
    )


__all__ = [
    "CanonicalEvent",
    "DocumentChanged",
    "EVENT_TYPE_TO_MODEL",
    "ExecutionCompleted",
    "ExecutionRequested",
    "ExecutionStarted",
    "FeedbackVerdict",
    "HumanFeedbackReceived",
    "KnowledgeConflictDetected",
    "ObservationAcknowledged",
    "ObservationCreated",
    "ObservationResolved",
    "ProjectCreated",
    "PullRequestCreated",
    "PullRequestRequested",
    "RepositoryRegistered",
    "RepositoryRevisionChanged",
    "RequirementChanged",
    "VerificationCompleted",
    "VerificationRequested",
    "WorkItemAssigned",
    "WorkItemChanged",
    "WorkItemCreated",
    "derive_event",
    "event_to_model",
    "model_to_envelope",
]
