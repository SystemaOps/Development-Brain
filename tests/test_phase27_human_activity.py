"""Phase 27 golden tests and completion gate.

Important Brain findings can appear as comments in OpenProject, while the same
application logic remains compatible with Jira or no human tool: the
HumanActivityPort is interchangeable, projection is idempotent, and human
replies normalize to HumanFeedbackReceived.
"""

from __future__ import annotations

import uuid

from brain.adapters.human_activity.jira import JiraActivityAdapter
from brain.adapters.human_activity.openproject import OpenProjectActivityAdapter
from brain.adapters.in_memory.human_activity import (
    InMemoryActivityProjectionRepository,
    NullHumanActivityPort,
)
from brain.adapters.in_memory.observations import InMemoryObservationRepository
from brain.application.observation_projection import ObservationProjectionService
from brain.domain.external_reference import ExternalReference
from brain.domain.human_activity import ProjectionStatus
from brain.domain.identity import ProjectId
from brain.domain.observations import Observation, ObservationType


class _FakeOpenProjectTransport:
    def __init__(self) -> None:
        self.comments: list[tuple[str, str]] = []

    async def post_comment(self, external_id: str, body: str) -> dict[str, object]:
        self.comments.append((external_id, body))
        return {"id": f"comment-{len(self.comments)}"}


class _FakeJiraTransport:
    def __init__(self) -> None:
        self.comments: list[tuple[str, str]] = []

    async def add_comment(self, issue_key: str, body: str) -> dict[str, object]:
        self.comments.append((issue_key, body))
        return {"id": f"jira-comment-{len(self.comments)}"}


def _observation(observation_type: ObservationType = ObservationType.DISCOVERY) -> Observation:
    return Observation(
        project_id=ProjectId(uuid.uuid4()),
        observation_type=observation_type,
        title="Login-attempt tracking already exists in AuthenticationService",
        body="Remaining work appears limited to account-lock enforcement and tests.",
    )


async def test_gate_openproject_projection_publishes_comment() -> None:
    transport = _FakeOpenProjectTransport()
    adapter = OpenProjectActivityAdapter(transport=transport)
    observations = InMemoryObservationRepository()
    projections = InMemoryActivityProjectionRepository()
    service = ObservationProjectionService(
        projections=projections,
        port=adapter,
        observations=observations,
    )
    observation = _observation()
    await observations.save(observation)

    reference = await service.project(
        observation,
        ExternalReference(provider="openproject", external_id="42"),
    )
    assert reference.status == ProjectionStatus.PUBLISHED
    assert reference.external_activity_id == "comment-1"
    assert transport.comments == [
        (
            "42",
            "Brain observation — discovery\n\n"
            "Login-attempt tracking already exists in AuthenticationService\n\n"
            "Remaining work appears limited to account-lock enforcement and tests.",
        )
    ]


async def test_gate_projection_is_idempotent() -> None:
    """Re-projecting the same observation must not create a duplicate comment."""
    transport = _FakeOpenProjectTransport()
    adapter = OpenProjectActivityAdapter(transport=transport)
    observations = InMemoryObservationRepository()
    projections = InMemoryActivityProjectionRepository()
    service = ObservationProjectionService(
        projections=projections,
        port=adapter,
        observations=observations,
    )
    observation = _observation()
    await observations.save(observation)
    target = ExternalReference(provider="openproject", external_id="42")

    first = await service.project(observation, target)
    second = await service.project(observation, target)
    assert first.id == second.id
    assert len(transport.comments) == 1  # no duplicate comment


async def test_gate_jira_adapter_is_interchangeable() -> None:
    """The same application logic works through Jira's adapter."""
    transport = _FakeJiraTransport()
    adapter = JiraActivityAdapter(transport=transport)
    observations = InMemoryObservationRepository()
    projections = InMemoryActivityProjectionRepository()
    service = ObservationProjectionService(
        projections=projections,
        port=adapter,
        observations=observations,
    )
    observation = _observation()
    await observations.save(observation)

    reference = await service.project(
        observation,
        ExternalReference(provider="jira", external_id="BRAIN-1"),
    )
    assert reference.status == ProjectionStatus.PUBLISHED
    assert transport.comments[0][0] == "BRAIN-1"


async def test_gate_null_adapter_noops_without_human_tool() -> None:
    """With no human tool configured, the observation stays stored and the
    projection safely no-ops."""
    observations = InMemoryObservationRepository()
    projections = InMemoryActivityProjectionRepository()
    service = ObservationProjectionService(
        projections=projections,
        port=NullHumanActivityPort(),
        observations=observations,
    )
    observation = _observation()
    await observations.save(observation)

    reference = await service.project(
        observation,
        ExternalReference(provider="openproject", external_id="42"),
    )
    assert reference.status == ProjectionStatus.SKIPPED
    # The observation remains stored.
    stored = await observations.get(observation.id)
    assert stored is not None


async def test_gate_provider_mismatch_fails_cleanly() -> None:
    transport = _FakeOpenProjectTransport()
    adapter = OpenProjectActivityAdapter(transport=transport)
    observations = InMemoryObservationRepository()
    projections = InMemoryActivityProjectionRepository()
    service = ObservationProjectionService(
        projections=projections,
        port=adapter,
        observations=observations,
    )
    observation = _observation()
    await observations.save(observation)

    reference = await service.project(
        observation,
        ExternalReference(provider="jira", external_id="X"),
    )
    assert reference.status == ProjectionStatus.FAILED
    assert "provider mismatch" in (reference.error or "")


async def test_gate_human_feedback_normalization_and_resume() -> None:
    """A human reply normalizes to HumanFeedbackReceived and resumes the
    workflow by invalidating stale context."""
    from brain.adapters.in_memory.context import InMemoryContextCapsuleRepository
    from brain.adapters.in_memory.event_bus import InMemoryEventBus
    from brain.adapters.in_memory.repositories import (
        InMemoryDecisionRepository,
        InMemoryRequirementRepository,
        InMemoryWorkItemRepository,
    )
    from brain.application.human_feedback import HumanFeedbackService
    from brain.domain.context import ContextRequest, PlanningContextCapsule
    from brain.domain.events import EventType
    from brain.domain.work_items import WorkItem

    work_items = InMemoryWorkItemRepository()
    requirements = InMemoryRequirementRepository()
    decisions = InMemoryDecisionRepository()
    capsules = InMemoryContextCapsuleRepository()
    bus = InMemoryEventBus()
    service = HumanFeedbackService(
        work_items=work_items,
        requirements=requirements,
        decisions=decisions,
        capsules=capsules,
        event_bus=bus,
    )

    project_id = ProjectId(uuid.uuid4())
    work_item = WorkItem(project_id=project_id, title="Task")
    await work_items.create(work_item)

    feedback = await service.receive(
        author="alice",
        provider="openproject",
        external_comment_id="c-1",
        work_item_id=work_item.id,
        message="Please clarify the lockout policy.",
        verdict="needs_clarification",
    )
    assert feedback.external_comment_id == "c-1"
    assert any(
        envelope.event_type == EventType.HUMAN_FEEDBACK_RECEIVED for envelope in bus.published
    )

    # Resuming invalidates stale context capsules for the work item.
    capsule = await capsules.save_capsule(
        PlanningContextCapsule(
            work_item_id=work_item.id,
            request=ContextRequest(work_item_id=work_item.id, project_id=project_id),
        )
    )
    result = await service.resume_workflow(feedback, verdict="needs_clarification")
    assert result["status"] == "resumed"
    assert result["context_invalidated"] is True
    assert await capsules.get_capsule(capsule.id) is None
