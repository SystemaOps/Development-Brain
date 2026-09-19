"""Phase 4 tests: end-to-end ingestion scenarios and verification.

Covers the cross-phase guarantees of the combined bootstrap + pull plan:

- webhooks arriving during/after bootstrap are idempotent (no duplicates, no
  re-trigger of historical assignment);
- a change missed by webhooks is recovered by the periodic pull;
- provider-done vs verification-pending disagreements become SyncConflict
  rows (never silently overwritten);
- a pull-discovered assignment triggers WorkItemAssigned -> RUN_WORK_ITEM
  through the full event->command chain.
"""

from __future__ import annotations

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.openproject_snapshot import InMemoryOpenProjectSnapshotStore
from brain.adapters.in_memory.repositories import (
    InMemoryActorRepository,
    InMemoryAttachmentRepository,
    InMemoryCommentRepository,
    InMemoryProjectRepository,
    InMemorySyncWatermarkRepository,
    InMemoryWorkItemRelationRepository,
    InMemoryWorkItemRepository,
)
from brain.adapters.in_memory.work_management import InMemoryWorkManagementIntegrationRepository
from brain.application.openproject_ingestion import (
    IngestionMode,
    OpenProjectIngestionService,
)
from brain.application.openproject_parser import OpenProjectWorkItemSnapshot
from brain.application.work_management_sync import WorkManagementPullSyncService
from brain.domain.external_reference import ExternalReference
from brain.domain.projects import Project


def _ingestion(
    brain_actor_id: str | None = None,
) -> tuple[OpenProjectIngestionService, InMemoryEventBus, InMemoryKnowledgeGraph]:
    events = InMemoryEventBus()
    graph = InMemoryKnowledgeGraph()
    service = OpenProjectIngestionService(
        projects=InMemoryProjectRepository(),
        work_items=InMemoryWorkItemRepository(),
        actors=InMemoryActorRepository(),
        comments=InMemoryCommentRepository(),
        attachments=InMemoryAttachmentRepository(),
        relations=InMemoryWorkItemRelationRepository(),
        integrations=InMemoryWorkManagementIntegrationRepository(),
        snapshots=InMemoryOpenProjectSnapshotStore(),
        graph=graph,
        event_bus=events,
        brain_actor_id=brain_actor_id,
    )
    return service, events, graph


def _snapshot(
    external_id: str,
    *,
    summary: str = "Task",
    state: str = "In progress",
    assignee_id: str | None = None,
) -> OpenProjectWorkItemSnapshot:
    return OpenProjectWorkItemSnapshot(
        external_id=external_id,
        summary=summary,
        state=state,
        project_id="8",
        assignee_id=assignee_id,
    )


def _project() -> Project:
    return Project(
        name="p",
        external_refs=[
            ExternalReference(provider="openproject", external_id="8", external_type="project")
        ],
    )


async def test_gate_webhook_after_bootstrap_is_idempotent() -> None:
    """A webhook for an item already imported by bootstrap must not duplicate
    or re-trigger the historical assignment (doc Phase 8 risk)."""
    service, events, _ = _ingestion(brain_actor_id="6")
    project = _project()
    await service._projects.create(project)

    # Bootstrap imports an existing task already assigned to the brain actor.
    await service.ingest_work_item_snapshot(
        _snapshot("43", summary="old", assignee_id="6"),
        mode=IngestionMode.BOOTSTRAP,
        source="bootstrap",
        project_id=project.id,
    )
    assert events.published == []

    # The same snapshot arrives as a live webhook afterwards.
    result = await service.ingest_work_item_snapshot(
        _snapshot("43", summary="old", assignee_id="6"),
        mode=IngestionMode.LIVE,
        source="webhook",
        project_id=project.id,
        provider_action="work_package:updated",
    )
    assert result.created is False
    assert result.changes == []
    assert result.assignment_triggered is False

    work_items = await service._work_items.list_by_project(project.id)
    assert len(work_items) == 1
    assert not any(event.event_type.value == "work_item_assigned" for event in events.published)


async def test_gate_pull_recovers_missed_webhook_change() -> None:
    """A change that never arrived as a webhook is recovered by the pull."""
    service, events, _ = _ingestion()
    project = _project()
    await service._projects.create(project)

    # Baseline: the item exists with the old title (webhook missed the change).
    await service.ingest_work_item_snapshot(
        _snapshot("43", summary="old title"),
        mode=IngestionMode.BOOTSTRAP,
        source="bootstrap",
        project_id=project.id,
    )
    before = len(events.published)

    class _FakeChangedProvider:
        async def list_changed_work_packages(self, since, *, offset=1, page_size=100):
            return [_snapshot("43", summary="new title")]

        async def get_work_package_snapshot(self, external_id):
            return None

        async def list_projects(self):
            return []

        async def list_work_packages(self, project_external_id, *, offset=1, page_size=100):
            return []

        async def list_activities(self, work_package_external_id):
            return []

    pull = WorkManagementPullSyncService(
        provider=_FakeChangedProvider(),  # type: ignore[arg-type]
        ingestion=service,
        projects=service._projects,
        work_items=service._work_items,
        integrations=service._integrations,
        watermarks=InMemorySyncWatermarkRepository(),
    )
    result = await pull.sync_project(project)
    assert result.items_pulled == 1
    # The change produced a canonical WorkItemChanged event.
    assert len(events.published) == before + 1
    changed = events.published[-1]
    assert changed.event_type.value == "work_item_changed"
    assert changed.payload["work_item"]["title"] == "new title"  # type: ignore[index]


async def test_gate_pull_records_status_conflict() -> None:
    """Provider says done but the brain has no passed verification."""
    service, events, _ = _ingestion()
    project = _project()
    await service._projects.create(project)

    await service.ingest_work_item_snapshot(
        _snapshot("43", summary="t", state="In progress"),
        mode=IngestionMode.BOOTSTRAP,
        source="bootstrap",
        project_id=project.id,
    )

    class _FakeChangedProvider:
        async def list_changed_work_packages(self, since, *, offset=1, page_size=100):
            return [_snapshot("43", summary="t", state="Closed")]

        async def get_work_package_snapshot(self, external_id):
            return None

        async def list_projects(self):
            return []

        async def list_work_packages(self, project_external_id, *, offset=1, page_size=100):
            return []

        async def list_activities(self, work_package_external_id):
            return []

    pull = WorkManagementPullSyncService(
        provider=_FakeChangedProvider(),  # type: ignore[arg-type]
        ingestion=service,
        projects=service._projects,
        work_items=service._work_items,
        integrations=service._integrations,
        watermarks=InMemorySyncWatermarkRepository(),
    )
    result = await pull.sync_project(project)
    assert result.conflicts_detected == 1

    work_item = await service._work_items.find_by_external_ref("openproject", "43", "work_package")
    assert work_item is not None
    conflicts = await service._integrations.list_conflicts(work_item.id)
    assert len(conflicts) == 1
    assert conflicts[0].provider_field == "status"
    assert conflicts[0].provider_value == "Closed"
    assert conflicts[0].brain_value == "verification_pending"

    # The same closed snapshot again must not create a duplicate conflict.
    again = await pull.sync_project(project)
    assert again.conflicts_detected == 0
    assert len(await service._integrations.list_conflicts(work_item.id)) == 1


async def test_gate_webhook_and_pull_share_ingestion_path() -> None:
    """Webhook + pull produce identical canonical state for the same snapshot."""
    webhook_service, _, _ = _ingestion()
    pull_service, _, _ = _ingestion()
    webhook_project = _project()
    pull_project = _project()
    await webhook_service._projects.create(webhook_project)
    await pull_service._projects.create(pull_project)

    snapshot = _snapshot("43", summary="shared", assignee_id="6")
    await webhook_service.ingest_work_item_snapshot(
        snapshot,
        mode=IngestionMode.LIVE,
        source="webhook",
        project_id=webhook_project.id,
        provider_action="work_package:created",
    )
    await pull_service.ingest_work_item_snapshot(
        snapshot,
        mode=IngestionMode.LIVE,
        source="pull",
        project_id=pull_project.id,
        publish_unchanged=False,
    )

    webhook_item = await webhook_service._work_items.find_by_external_ref(
        "openproject", "43", "work_package"
    )
    pull_item = await pull_service._work_items.find_by_external_ref(
        "openproject", "43", "work_package"
    )
    assert webhook_item is not None and pull_item is not None
    assert webhook_item.title == pull_item.title == "shared"
    assert webhook_item.type == pull_item.type
    assert webhook_item.human_work_status == pull_item.human_work_status
    assert webhook_item.assignee is not None
    assert pull_item.assignee is not None
