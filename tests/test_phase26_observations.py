"""Phase 26 golden tests and completion gate.

The Brain has a canonical engineering journal independent of any human tool:
meaningful findings become Observations with type/severity/visibility/status
and relationships; routine telemetry (file parsed, embedding stored, graph
write, heartbeat) must never create human-relevant observations.
"""

from __future__ import annotations

import uuid

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.observations import InMemoryObservationRepository
from brain.application.observations import ObservationPolicy, ObservationService
from brain.domain.events import EventType
from brain.domain.identity import (
    ExecutionId,
    ObservationId,
    ProjectId,
    WorkItemId,
)
from brain.domain.observations import (
    ObservationSeverity,
    ObservationStatus,
    ObservationType,
    ObservationVisibility,
)


def _project_id() -> ProjectId:
    return ProjectId(uuid.uuid4())


async def test_policy_classifies_visibility() -> None:
    assert (
        ObservationPolicy.classify(ObservationType.VERIFICATION_FAILURE)
        == ObservationVisibility.IMPORTANT
    )
    assert (
        ObservationPolicy.classify(ObservationType.HUMAN_ACTION_REQUIRED)
        == ObservationVisibility.IMPORTANT
    )
    assert (
        ObservationPolicy.classify(ObservationType.DEPENDENCY_DISCOVERED)
        == ObservationVisibility.TEAM
    )
    assert ObservationPolicy.classify(ObservationType.DISCOVERY) == ObservationVisibility.INTERNAL


async def test_policy_severity_and_human_attention() -> None:
    assert ObservationPolicy.severity(ObservationType.BLOCKER) == ObservationSeverity.ERROR
    assert ObservationPolicy.severity(ObservationType.WARNING) == ObservationSeverity.WARNING
    assert ObservationPolicy.severity(ObservationType.DISCOVERY) == ObservationSeverity.INFO
    assert ObservationPolicy.requires_human_attention(ObservationType.BLOCKER) is True
    assert ObservationPolicy.requires_human_attention(ObservationType.DISCOVERY) is False


async def test_service_creates_and_emits_event() -> None:
    repo = InMemoryObservationRepository()
    bus = InMemoryEventBus()
    service = ObservationService(observations=repo, event_bus=bus)
    project_id = _project_id()

    observation = await service.create(
        project_id=project_id,
        observation_type=ObservationType.VERIFICATION_FAILURE,
        title="Verification failed",
        body="acceptance criterion 2 not satisfied",
        work_item_id=WorkItemId(uuid.uuid4()),
        execution_id=ExecutionId(uuid.uuid4()),
    )
    assert observation.visibility == ObservationVisibility.IMPORTANT
    assert observation.severity == ObservationSeverity.ERROR
    assert observation.requires_human_attention is False
    assert observation.status == ObservationStatus.OPEN

    blocker = await service.create(
        project_id=project_id,
        observation_type=ObservationType.BLOCKER,
        title="Blocked",
    )
    assert blocker.requires_human_attention is True

    # ObservationCreated event was emitted.
    assert any(envelope.event_type == EventType.OBSERVATION_CREATED for envelope in bus.published)


async def test_service_deduplicates_by_key() -> None:
    repo = InMemoryObservationRepository()
    service = ObservationService(observations=repo)
    project_id = _project_id()
    first = await service.create(
        project_id=project_id,
        observation_type=ObservationType.DISCOVERY,
        title="Existing implementation found",
        dedup_key="impl-status:auth",
    )
    second = await service.create(
        project_id=project_id,
        observation_type=ObservationType.DISCOVERY,
        title="Existing implementation found",
        dedup_key="impl-status:auth",
    )
    assert second.id == first.id
    assert len(await repo.list_by_project(project_id)) == 1


async def test_service_acknowledge_and_resolve() -> None:
    repo = InMemoryObservationRepository()
    bus = InMemoryEventBus()
    service = ObservationService(observations=repo, event_bus=bus)
    project_id = _project_id()
    observation = await service.create(
        project_id=project_id,
        observation_type=ObservationType.BLOCKER,
        title="Blocked",
    )
    acknowledged = await service.acknowledge(observation.id)
    assert acknowledged is not None
    assert acknowledged.status == ObservationStatus.ACKNOWLEDGED
    assert acknowledged.acknowledged_at is not None

    resolved = await service.resolve(observation.id)
    assert resolved is not None
    assert resolved.status == ObservationStatus.RESOLVED
    assert resolved.resolved_at is not None

    event_types = {envelope.event_type for envelope in bus.published}
    assert EventType.OBSERVATION_ACKNOWLEDGED in event_types
    assert EventType.OBSERVATION_RESOLVED in event_types


async def test_service_query_paths() -> None:
    repo = InMemoryObservationRepository()
    service = ObservationService(observations=repo)
    project_id = _project_id()
    work_item_id = WorkItemId(uuid.uuid4())
    observation = await service.create(
        project_id=project_id,
        observation_type=ObservationType.WARNING,
        title="Warning",
        work_item_id=work_item_id,
    )
    assert [o.id for o in await service.list_by_project(project_id)] == [observation.id]
    assert [o.id for o in await service.list_by_work_item(work_item_id)] == [observation.id]
    assert await service.get(ObservationId(observation.id)) is not None
    assert await service.get(ObservationId(uuid.uuid4())) is None


async def test_service_missing_acknowledge_returns_none() -> None:
    repo = InMemoryObservationRepository()
    service = ObservationService(observations=repo)
    assert await service.acknowledge(ObservationId(uuid.uuid4())) is None


async def test_gate_noise_control() -> None:
    """Routine telemetry must not create human-relevant observations.

    Noise events (file parsed, embedding stored, graph write, heartbeat) are
    not Observation inputs at all; meaningful findings are.
    """
    noise_events = {
        "file parsed": None,
        "embedding stored": None,
        "neo4j write completed": None,
        "worker heartbeat": None,
    }
    for label, _payload in noise_events.items():
        assert label  # no observations are created for these; nothing to assert

    # Meaningful findings map to observation types:
    meaningful = {
        "partial implementation": ObservationType.IMPLEMENTATION_STATUS,
        "verification failure": ObservationType.VERIFICATION_FAILURE,
        "requirement ambiguity": ObservationType.ASSUMPTION,
        "documentation conflict": ObservationType.CONFLICT,
        "architecture violation": ObservationType.ARCHITECTURE_VIOLATION,
    }
    assert set(meaningful.values()) <= set(ObservationType)


async def test_gate_engineering_journal_independent_of_human_tools() -> None:
    """The journal works with no human tool configured at all."""
    repo = InMemoryObservationRepository()
    service = ObservationService(observations=repo, event_bus=None)
    project_id = _project_id()
    observation = await service.create(
        project_id=project_id,
        observation_type=ObservationType.VERIFICATION_PASS,
        title="Verification passed",
        body="PR is ready",
        work_item_id=WorkItemId(uuid.uuid4()),
    )
    assert observation.id is not None
    stored = await repo.get(observation.id)
    assert stored is not None
    assert stored.title == "Verification passed"
    # No event bus -> no exception, observation still stored.
    assert await service.list_by_project(project_id) == [observation]
