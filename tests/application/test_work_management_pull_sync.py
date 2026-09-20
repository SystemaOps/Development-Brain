"""Phase 3 tests: work-management pull reconciliation service.

Periodic pulls diff against the durable watermark, ingest changed work
packages through the unified ingestion service (LIVE mode), advance the
watermark after the batch, and sweep previously-mapped items missing from the
updated-since window.  Unchanged snapshots emit no events; the first pull
after bootstrap starts with a small overlap.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
from brain.application.openproject_ingestion import OpenProjectIngestionService
from brain.application.openproject_parser import OpenProjectWorkItemSnapshot
from brain.application.work_management_sync import WorkManagementPullSyncService
from brain.domain.external_reference import ExternalReference
from brain.domain.projects import Project
from brain.domain.sync_watermark import ProviderSyncWatermark
from brain.domain.work_items import WorkItem


class _FakeChangedProvider:
    """WorkManagementBootstrapPort fake with an updated-since page stream."""

    def __init__(
        self,
        changed: list[OpenProjectWorkItemSnapshot] | None = None,
        snapshots_by_id: dict[str, OpenProjectWorkItemSnapshot] | None = None,
    ) -> None:
        self._changed = changed or []
        self._by_id = snapshots_by_id or {}
        self.page_calls: list[tuple[datetime | None, int]] = []

    async def list_changed_work_packages(
        self,
        since: datetime,
        *,
        offset: int = 1,
        page_size: int = 100,
        project_external_id: str | None = None,
    ) -> list[OpenProjectWorkItemSnapshot]:
        self.page_calls.append((since, offset))
        start = offset - 1
        return self._changed[start : start + page_size]

    async def get_work_package_snapshot(
        self, external_id: str
    ) -> OpenProjectWorkItemSnapshot | None:
        return self._by_id.get(external_id)

    async def list_projects(self):  # pragma: no cover - bootstrap surface
        return []

    async def list_work_packages(
        self, project_external_id, *, offset=1, page_size=100
    ):  # pragma: no cover
        return []

    async def list_activities(self, work_package_external_id):  # pragma: no cover
        return []


def _build_pull_service(
    provider: _FakeChangedProvider,
    *,
    page_size: int = 100,
    since_days: int = 1,
    sweep_limit: int = 20,
) -> tuple[WorkManagementPullSyncService, InMemoryEventBus]:
    projects = InMemoryProjectRepository()
    work_items = InMemoryWorkItemRepository()
    integrations = InMemoryWorkManagementIntegrationRepository()
    watermarks = InMemorySyncWatermarkRepository()
    events = InMemoryEventBus()
    graph = InMemoryKnowledgeGraph()
    ingestion = OpenProjectIngestionService(
        projects=projects,
        work_items=work_items,
        actors=InMemoryActorRepository(),
        comments=InMemoryCommentRepository(),
        attachments=InMemoryAttachmentRepository(),
        relations=InMemoryWorkItemRelationRepository(),
        integrations=integrations,
        snapshots=InMemoryOpenProjectSnapshotStore(),
        graph=graph,
        event_bus=events,
    )
    service = WorkManagementPullSyncService(
        provider=provider,
        ingestion=ingestion,
        projects=projects,
        work_items=work_items,
        integrations=integrations,
        watermarks=watermarks,
        page_size=page_size,
        since_days=since_days,
        sweep_limit=sweep_limit,
    )
    return service, events


def _project() -> Project:
    return Project(
        name="p",
        external_refs=[
            ExternalReference(provider="openproject", external_id="8", external_type="project")
        ],
    )


def _snapshot(
    external_id: str, *, summary: str = "Task", assignee_id: str | None = None
) -> OpenProjectWorkItemSnapshot:
    return OpenProjectWorkItemSnapshot(
        external_id=external_id,
        summary=summary,
        state="In progress",
        project_id="8",
        assignee_id=assignee_id,
    )


async def test_gate_pull_ingests_changed_items_and_advances_watermark() -> None:
    provider = _FakeChangedProvider(
        changed=[_snapshot("1", summary="a"), _snapshot("2", summary="b")]
    )
    service, events = _build_pull_service(provider)
    project = _project()
    await service._projects.create(project)

    result = await service.sync_project(project)
    assert result.status == "ok"
    assert result.items_pulled == 2
    assert result.items_created == 2

    stored = await service._work_items.list_by_project(project.id)
    assert len(stored) == 2
    # Created items publish canonical events.
    assert any(event.event_type.value == "work_item_created" for event in events.published)

    watermark = await service._watermarks.get_or_create("openproject", "work_items:8")
    assert watermark.last_synced_at is not None
    assert watermark.last_external_id == "2"
    # The window started at now - since_days (no prior state).
    since, _ = provider.page_calls[0]
    assert since is not None
    assert datetime.now(UTC) - since <= timedelta(days=1, seconds=1)


async def test_gate_pull_unchanged_items_emit_no_events() -> None:
    provider = _FakeChangedProvider(changed=[_snapshot("1", summary="a")])
    service, events = _build_pull_service(provider)
    project = _project()
    await service._projects.create(project)

    await service.sync_project(project)
    first_event_count = len(events.published)
    assert first_event_count == 1

    # Same snapshot again: diff is empty -> no events, watermark refreshed.
    provider._changed = [_snapshot("1", summary="a")]
    result = await service.sync_project(project)
    assert result.items_pulled == 1
    assert len(events.published) == first_event_count


async def test_gate_pull_overlap_after_bootstrap() -> None:
    provider = _FakeChangedProvider(changed=[])
    service, _ = _build_pull_service(provider)
    project = _project()
    await service._projects.create(project)

    completed = datetime.now(UTC) - timedelta(minutes=10)
    await service._watermarks.save(
        ProviderSyncWatermark(
            provider="openproject",
            sync_key="work_items:8",
            bootstrap_completed_at=completed,
        )
    )
    await service.sync_project(project)
    since, _ = provider.page_calls[0]
    assert since is not None
    # Overlap: the first pull starts slightly before bootstrap completion.
    assert completed - since <= timedelta(seconds=5, microseconds=1000)
    assert since <= completed


async def test_gate_pull_uses_previous_watermark_as_since() -> None:
    provider = _FakeChangedProvider(changed=[_snapshot("2", summary="b")])
    service, _ = _build_pull_service(provider)
    project = _project()
    await service._projects.create(project)

    previous = datetime.now(UTC) - timedelta(hours=3)
    await service._watermarks.save(
        ProviderSyncWatermark(
            provider="openproject",
            sync_key="work_items:8",
            last_synced_at=previous,
        )
    )
    await service.sync_project(project)
    since, _ = provider.page_calls[0]
    assert since is not None
    assert since == previous


async def test_gate_pull_sweeps_missing_mapped_items() -> None:
    snapshot_50 = _snapshot("50", summary="old item")
    provider = _FakeChangedProvider(changed=[], snapshots_by_id={"50": snapshot_50})
    service, _ = _build_pull_service(provider)
    project = _project()
    await service._projects.create(project)

    # A previously-mapped work item exists but never appears in the window.
    work_item = WorkItem(
        project_id=project.id,
        title="old item",
        external_refs=[
            ExternalReference(
                provider="openproject", external_id="50", external_type="work_package"
            )
        ],
    )
    await service._work_items.create(work_item)
    await service._watermarks.save(
        ProviderSyncWatermark(
            provider="openproject",
            sync_key="work_items:8",
            last_synced_at=datetime.now(UTC) - timedelta(minutes=30),
        )
    )

    result = await service.sync_project(project)
    assert result.items_swept == 1
    stored = await service._work_items.get(work_item.id)
    assert stored is not None
    assert stored.human_work_status.value == "in_progress"


async def test_gate_pull_skips_project_without_provider_ref() -> None:
    service, _ = _build_pull_service(_FakeChangedProvider())
    project = Project(name="no-ref")
    await service._projects.create(project)

    result = await service.sync_project(project)
    assert result.status == "no_provider_ref"
    assert result.items_pulled == 0


async def test_gate_pull_paginates() -> None:
    provider = _FakeChangedProvider(
        changed=[_snapshot(str(i), summary=f"t{i}") for i in range(1, 12)]
    )
    service, _ = _build_pull_service(provider, page_size=5)
    project = _project()
    await service._projects.create(project)

    result = await service.sync_project(project)
    assert result.items_pulled == 11
    assert result.pages_fetched == 3
    assert [offset for _, offset in provider.page_calls] == [1, 6, 11]
