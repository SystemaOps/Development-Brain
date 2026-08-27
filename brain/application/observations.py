"""Observation service and policy (Phase 26).

``ObservationService`` provides create (with deduplication), query,
acknowledge, and resolve on the canonical engineering journal, emitting
``ObservationCreated`` / ``ObservationAcknowledged`` / ``ObservationResolved``
events (Task 26.7).  ``ObservationPolicy`` applies deterministic visibility
rules: important findings (verification failures, blockers, human action
required, conflicts, architecture violations) become IMPORTANT / require human
attention; routine discoveries stay INTERNAL (Task 26.6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from brain.domain.events import EventEnvelope, EventType
from brain.domain.identity import (
    ActorId,
    ArtifactId,
    ContextCapsuleId,
    DecisionId,
    EvidenceId,
    ExecutionId,
    ObservationId,
    ProjectId,
    RepositoryId,
    RequirementId,
    VerificationId,
    WorkItemId,
)
from brain.domain.observations import (
    Observation,
    ObservationSeverity,
    ObservationStatus,
    ObservationType,
    ObservationVisibility,
)
from brain.ports.event_bus import EventBus
from brain.ports.observations import ObservationRepository


class ObservationPolicy:
    """Deterministic observation visibility/severity rules (Task 26.6)."""

    IMPORTANT_TYPES = {
        ObservationType.BLOCKER,
        ObservationType.HUMAN_ACTION_REQUIRED,
        ObservationType.ARCHITECTURE_VIOLATION,
        ObservationType.VERIFICATION_FAILURE,
        ObservationType.CONFLICT,
    }

    @classmethod
    def classify(cls, observation_type: ObservationType) -> ObservationVisibility:
        if observation_type in cls.IMPORTANT_TYPES:
            return ObservationVisibility.IMPORTANT
        if observation_type in {
            ObservationType.WARNING,
            ObservationType.SCOPE_CHANGE,
            ObservationType.DEPENDENCY_DISCOVERED,
            ObservationType.IMPLEMENTATION_STATUS,
        }:
            return ObservationVisibility.TEAM
        return ObservationVisibility.INTERNAL

    @classmethod
    def severity(cls, observation_type: ObservationType) -> ObservationSeverity:
        if observation_type in cls.IMPORTANT_TYPES:
            return ObservationSeverity.ERROR
        if observation_type in {
            ObservationType.WARNING,
            ObservationType.SCOPE_CHANGE,
            ObservationType.DEPENDENCY_DISCOVERED,
        }:
            return ObservationSeverity.WARNING
        return ObservationSeverity.INFO

    @classmethod
    def requires_human_attention(cls, observation_type: ObservationType) -> bool:
        return observation_type in {
            ObservationType.HUMAN_ACTION_REQUIRED,
            ObservationType.BLOCKER,
        }


class ObservationService:
    """Canonical engineering journal operations."""

    def __init__(
        self,
        *,
        observations: ObservationRepository,
        event_bus: EventBus | None = None,
    ) -> None:
        self._observations = observations
        self._event_bus = event_bus

    async def create(
        self,
        *,
        project_id: ProjectId,
        observation_type: ObservationType,
        title: str,
        body: str = "",
        work_item_id: WorkItemId | None = None,
        execution_id: ExecutionId | None = None,
        requirement_id: RequirementId | None = None,
        repository_id: RepositoryId | None = None,
        repository_revision: str | None = None,
        context_capsule_id: ContextCapsuleId | None = None,
        verification_id: VerificationId | None = None,
        artifact_id: ArtifactId | None = None,
        evidence_id: EvidenceId | None = None,
        decision_id: DecisionId | None = None,
        evidence_refs: list[uuid.UUID] | None = None,
        source: str = "brain",
        dedup_key: str | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> Observation:
        """Create an observation, deduplicating by ``dedup_key`` (Task 26.5)."""
        if dedup_key is not None:
            existing = await self._observations.find_by_dedup_key(dedup_key)
            if existing is not None:
                return existing

        observation = Observation(
            project_id=project_id,
            work_item_id=work_item_id,
            execution_id=execution_id,
            requirement_id=requirement_id,
            repository_id=repository_id,
            repository_revision=repository_revision,
            context_capsule_id=context_capsule_id,
            verification_id=verification_id,
            artifact_id=artifact_id,
            evidence_id=evidence_id,
            decision_id=decision_id,
            observation_type=observation_type,
            severity=ObservationPolicy.severity(observation_type),
            visibility=ObservationPolicy.classify(observation_type),
            title=title,
            body=body,
            source=source,
            evidence_refs=evidence_refs or [],
            requires_human_attention=ObservationPolicy.requires_human_attention(observation_type),
            dedup_key=dedup_key,
        )
        await self._observations.save(observation)
        await self._emit(
            EventType.OBSERVATION_CREATED,
            observation,
            correlation_id=correlation_id,
        )
        return observation

    async def get(self, observation_id: ObservationId) -> Observation | None:
        return await self._observations.get(observation_id)

    async def list_by_project(self, project_id: ProjectId) -> list[Observation]:
        return await self._observations.list_by_project(project_id)

    async def list_by_work_item(self, work_item_id: WorkItemId) -> list[Observation]:
        return await self._observations.list_by_work_item(work_item_id)

    async def list_recent(self, limit: int = 100) -> list[Observation]:
        return await self._observations.list_recent(limit=limit)

    async def acknowledge(
        self,
        observation_id: ObservationId,
        *,
        acknowledged_by: ActorId | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> Observation | None:
        observation = await self._observations.get(observation_id)
        if observation is None:
            return None
        observation.status = ObservationStatus.ACKNOWLEDGED
        observation.acknowledged_at = datetime.now(UTC)
        await self._observations.save(observation)
        await self._emit(
            EventType.OBSERVATION_ACKNOWLEDGED,
            observation,
            correlation_id=correlation_id,
        )
        return observation

    async def resolve(
        self,
        observation_id: ObservationId,
        *,
        resolved_by: ActorId | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> Observation | None:
        observation = await self._observations.get(observation_id)
        if observation is None:
            return None
        observation.status = ObservationStatus.RESOLVED
        observation.resolved_at = datetime.now(UTC)
        await self._observations.save(observation)
        await self._emit(
            EventType.OBSERVATION_RESOLVED,
            observation,
            correlation_id=correlation_id,
        )
        return observation

    async def _emit(
        self,
        event_type: EventType,
        observation: Observation,
        *,
        correlation_id: uuid.UUID | None = None,
    ) -> None:
        if self._event_bus is None:
            return
        from brain.domain.event_types import (
            ObservationAcknowledged,
            ObservationCreated,
            ObservationResolved,
        )

        payload: dict[str, object]
        if event_type == EventType.OBSERVATION_CREATED:
            payload = ObservationCreated(
                observation_id=observation.id,
                project_id=observation.project_id,
                observation_type=observation.observation_type.value,
                title=observation.title,
                body=observation.body,
            ).to_payload()
        elif event_type == EventType.OBSERVATION_ACKNOWLEDGED:
            payload = ObservationAcknowledged(
                observation_id=observation.id,
                project_id=observation.project_id,
            ).to_payload()
        else:
            payload = ObservationResolved(
                observation_id=observation.id,
                project_id=observation.project_id,
            ).to_payload()
        envelope = EventEnvelope(
            event_type=event_type,
            project_id=observation.project_id,
            correlation_id=correlation_id or uuid.uuid4(),
            source="brain.observations",
            payload=payload,
        )
        await self._event_bus.publish(envelope)


__all__ = ["ObservationPolicy", "ObservationService"]
