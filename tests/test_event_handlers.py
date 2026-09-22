"""Phase 4 gate: event handlers decide consequences (docs/eventbus/PLAN.md).

Unit-level tests for the handlers in ``brain/application/event_handlers.py``
using in-memory repositories — no database required:

- ``WorkItemAssignedHandler`` enqueues RUN_WORK_ITEM on the assignment fact
- ``HumanFeedbackReceivedHandler`` resumes the workflow (invalidates capsules)
  without re-emitting the fact (no event loop)
- ``PullRequestMergedHandler`` publishes RepositoryRevisionChanged and
  enqueues re-ingestion
"""

from __future__ import annotations

from brain.adapters.in_memory.commands import InMemoryCommandQueue
from brain.adapters.in_memory.context import InMemoryContextCapsuleRepository
from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.repositories import (
    InMemoryDecisionRepository,
    InMemoryRequirementRepository,
    InMemoryWorkItemRepository,
)
from brain.application.event_handlers import (
    HumanFeedbackReceivedHandler,
    PullRequestMergedHandler,
    WorkItemAssignedHandler,
)
from brain.application.human_feedback import HumanFeedbackService
from brain.application.pull_request_service import PullRequestService
from brain.domain.commands import CommandType
from brain.domain.context import ContextRequest, PlanningContextCapsule
from brain.domain.event_types import (
    HumanFeedbackReceived,
    PullRequestMerged,
    WorkItemAssigned,
    model_to_envelope,
)
from brain.domain.events import EventType
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import new_project_id
from brain.domain.work_items import WorkItem


class _FakeContainer:
    """Minimal container surface: services + repositories used by handlers."""

    def __init__(self, services: dict[str, object], repositories: object) -> None:
        self.services = services
        self.repositories = repositories


async def _work_item_container() -> tuple[_FakeContainer, InMemoryCommandQueue, WorkItem]:
    queue = InMemoryCommandQueue()
    services: dict[str, object] = {"command_queue": queue}
    container = _FakeContainer(services=services, repositories=None)
    work_item = WorkItem(project_id=new_project_id(), title="Task")
    return container, queue, work_item


async def test_work_item_assigned_handler_enqueues_run_command() -> None:
    """WorkItemAssigned fact -> RUN_WORK_ITEM enqueued by the handler."""
    container, queue, work_item = await _work_item_container()
    handler = WorkItemAssignedHandler(container=container)  # type: ignore[arg-type]
    envelope = model_to_envelope(
        WorkItemAssigned(work_item_id=work_item.id, external_actor_id="6"),
        source="test",
    )
    await handler.handle(envelope)

    assert await queue.pending_count() == 1
    command = await queue.consume(timeout_seconds=0.1)
    assert command is not None
    assert command.command_type == CommandType.RUN_WORK_ITEM
    assert command.payload["work_item_id"] == str(work_item.id)
    await queue.acknowledge(command.command_id)


async def test_work_item_assigned_handler_ignores_other_events() -> None:
    """Non-matching events are ignored (no enqueue, no error)."""
    container, queue, _ = await _work_item_container()
    handler = WorkItemAssignedHandler(container=container)  # type: ignore[arg-type]
    await handler.handle(
        model_to_envelope(
            HumanFeedbackReceived(author="a", external_comment_id="c"),
            source="test",
        )
    )
    assert await queue.pending_count() == 0


async def test_human_feedback_handler_resumes_without_loop() -> None:
    """The feedback fact resumes the workflow and does not re-emit."""
    work_items = InMemoryWorkItemRepository()
    requirements = InMemoryRequirementRepository()
    decisions = InMemoryDecisionRepository()
    capsules = InMemoryContextCapsuleRepository()
    bus = InMemoryEventBus()
    feedback_service = HumanFeedbackService(
        work_items=work_items,
        requirements=requirements,
        decisions=decisions,
        capsules=capsules,
        event_bus=bus,
    )
    services: dict[str, object] = {"human_feedback": feedback_service}
    container = _FakeContainer(services=services, repositories=None)
    handler = HumanFeedbackReceivedHandler(container=container)  # type: ignore[arg-type]

    project_id = new_project_id()
    work_item = WorkItem(project_id=project_id, title="Task")
    await work_items.create(work_item)
    capsule = await capsules.save_capsule(
        PlanningContextCapsule(
            work_item_id=work_item.id,
            request=ContextRequest(work_item_id=work_item.id, project_id=project_id),
        )
    )

    envelope = model_to_envelope(
        HumanFeedbackReceived(
            work_item_id=work_item.id,
            author="alice",
            provider="openproject",
            external_comment_id="c-1",
            verdict="needs_changes",
            feedback="Please clarify the lockout policy.",
        ),
        source="test",
    )
    before = len(bus.published)
    await handler.handle(envelope)

    # Workflow resumed: stale context capsules invalidated.
    assert await capsules.get_capsule(capsule.id) is None
    # No re-emit of the fact: the handler must not trigger itself.
    assert len(bus.published) == before


async def test_pull_request_merged_handler_reingests() -> None:
    """PullRequestMerged fact -> revision changed + re-ingestion enqueued."""
    queue = InMemoryCommandQueue()
    bus = InMemoryEventBus()
    service = PullRequestService(
        container=_FakeContainer(  # type: ignore[arg-type]
            services={"events": bus, "command_queue": queue}, repositories=None
        )
    )
    services: dict[str, object] = {
        "command_queue": queue,
        "pull_request_service": service,
    }
    container = _FakeContainer(services=services, repositories=None)
    handler = PullRequestMergedHandler(container=container)  # type: ignore[arg-type]

    ref = ExternalReference(
        provider="gitlab",
        external_id="7",
        external_type="merge_request",
        namespace="1",
    )
    envelope = model_to_envelope(PullRequestMerged(external_ref=ref), source="test")
    await handler.handle(envelope)

    # Consequence applied: revision-changed fact published + re-ingestion
    # enqueued (the handler must not re-publish PullRequestMerged).
    types = [e.event_type for e in bus.published]
    assert EventType.REPOSITORY_REVISION_CHANGED in types
    assert EventType.PULL_REQUEST_MERGED not in types
    assert await queue.pending_count() == 1
    command = await queue.consume(timeout_seconds=0.1)
    assert command is not None
    assert command.command_type.value == "sync_repository"
    await queue.acknowledge(command.command_id)


async def test_handlers_are_subscribed_on_the_container_bus() -> None:
    """Integration: the composition root subscribes all three handlers."""
    from brain.api.app import create_app
    from brain.bootstrap.settings import (
        BrainSettings,
        DocumentationSettings,
        Neo4jSettings,
        PostgresSettings,
        RedisSettings,
        SourceControlSettings,
        VerificationSettings,
        WeaviateSettings,
        WorkManagementSettings,
    )
    from tests.conftest import postgres_reachable

    if not postgres_reachable("postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/brain"):
        import pytest

        pytest.skip("PostgreSQL is not available; start it with: docker compose up -d")

    settings = BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://127.0.0.1:7687"),
        storage_semantic=WeaviateSettings(host="127.0.0.1"),
        storage_queue=RedisSettings(url="redis://127.0.0.1:6379/0", provider="inmemory"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        bus = app.state.container.services["events"]
        handlers = getattr(bus, "_handlers", {})
        for event_type in (
            EventType.WORK_ITEM_ASSIGNED.value,
            EventType.HUMAN_FEEDBACK_RECEIVED.value,
            EventType.PULL_REQUEST_MERGED.value,
        ):
            assert event_type in handlers, f"{event_type} not subscribed"
            assert handlers[event_type], f"{event_type} has no handlers"
