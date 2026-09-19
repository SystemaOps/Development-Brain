"""Phase 2 tests: OpenProject existing-project bootstrap service.

An existing OpenProject project is imported without triggering workflows:
projects + hierarchy, all work packages (paginated), two-pass relations,
historical comments as context only, attachments, durable baseline snapshots
and the sync watermark.  Re-runs are idempotent; interrupted runs resume from
their checkpoint.
"""

from __future__ import annotations

import pytest

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.openproject_snapshot import InMemoryOpenProjectSnapshotStore
from brain.adapters.in_memory.repositories import (
    InMemoryActorRepository,
    InMemoryAttachmentRepository,
    InMemoryBootstrapStateRepository,
    InMemoryCommentRepository,
    InMemoryProjectRepository,
    InMemorySyncWatermarkRepository,
    InMemoryWorkItemRelationRepository,
    InMemoryWorkItemRepository,
)
from brain.adapters.in_memory.work_management import InMemoryWorkManagementIntegrationRepository
from brain.application.openproject_bootstrap import OpenProjectProjectBootstrapService
from brain.application.openproject_ingestion import (
    IngestionMode,
    OpenProjectIngestionService,
)
from brain.application.openproject_parser import OpenProjectWorkItemSnapshot
from brain.domain.bootstrap_state import BootstrapStatus
from brain.domain.projects import Project
from brain.ports.work_management_bootstrap import ProviderActivity, ProviderProject


class _FakeProvider:
    """WorkManagementBootstrapPort fake with a configurable payload."""

    def __init__(
        self,
        *,
        projects: list[ProviderProject] | None = None,
        work_packages: list[OpenProjectWorkItemSnapshot] | None = None,
        activities: dict[str, list[ProviderActivity]] | None = None,
        page_size: int = 100,
    ) -> None:
        self._projects = projects or []
        self._work_packages = work_packages or []
        self._activities = activities or {}
        self._page_size = page_size
        self.project_fetches = 0
        self.activity_fetches = 0

    async def list_projects(self) -> list[ProviderProject]:
        self.project_fetches += 1
        return self._projects

    async def list_work_packages(
        self,
        project_external_id: str,
        *,
        offset: int = 1,
        page_size: int = 100,
    ) -> list[OpenProjectWorkItemSnapshot]:
        del project_external_id
        start = offset - 1
        return self._work_packages[start : start + page_size]

    async def list_activities(self, work_package_external_id: str) -> list[ProviderActivity]:
        self.activity_fetches += 1
        return self._activities.get(work_package_external_id, [])


def _service_and_provider(
    *,
    projects: list[ProviderProject] | None = None,
    work_packages: list[OpenProjectWorkItemSnapshot] | None = None,
    activities: dict[str, list[ProviderActivity]] | None = None,
    page_size: int = 100,
    brain_actor_id: str | None = "6",
) -> tuple[
    OpenProjectProjectBootstrapService, _FakeProvider, InMemoryEventBus, InMemoryKnowledgeGraph
]:
    provider = _FakeProvider(
        projects=projects,
        work_packages=work_packages,
        activities=activities,
        page_size=page_size,
    )
    events = InMemoryEventBus()
    graph = InMemoryKnowledgeGraph()
    ingestion = OpenProjectIngestionService(
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
    service = OpenProjectProjectBootstrapService(
        provider=provider,
        ingestion=ingestion,
        bootstrap_states=InMemoryBootstrapStateRepository(),
        watermarks=InMemorySyncWatermarkRepository(),
        page_size=page_size,
    )
    return service, provider, events, graph


def _project(external_id: str, name: str, parent: str | None = None) -> ProviderProject:
    return ProviderProject(
        external_id=external_id,
        name=name,
        identifier=name.lower(),
        parent_external_id=parent,
    )


def _work_item(
    external_id: str,
    *,
    summary: str = "Task",
    assignee_id: str | None = None,
    parent_id: int | None = None,
) -> OpenProjectWorkItemSnapshot:
    return OpenProjectWorkItemSnapshot(
        external_id=external_id,
        summary=summary,
        state="In progress",
        project_id="8",
        assignee_id=assignee_id,
        parent_id=parent_id,
    )


def _activity(external_id: str, text: str, author: str = "alice") -> ProviderActivity:
    return ProviderActivity(external_id=external_id, author_name=author, text=text)


async def test_gate_bootstrap_imports_project_hierarchy() -> None:
    service, provider, events, _ = _service_and_provider(
        projects=[_project("8", "Root"), _project("9", "Sub", parent="8")],
        work_packages=[],
    )
    brain_project = Project(name="brain project")
    result = await service.bootstrap(project_id=brain_project.id, external_project_id="8")
    assert result.status == BootstrapStatus.READY
    assert result.projects_ingested == 2
    # No workflow events were emitted for historical state.
    assert events.published == []

    root = await service._ingestion._projects.find_by_external_ref("openproject", "8", "project")
    sub = await service._ingestion._projects.find_by_external_ref("openproject", "9", "project")
    assert root is not None and sub is not None
    assert sub.parent_id == root.id


async def test_gate_bootstrap_imports_all_work_items_with_pagination() -> None:
    work_packages = [_work_item(str(i), summary=f"task-{i}") for i in range(1, 13)]
    service, provider, _, _ = _service_and_provider(
        projects=[_project("8", "Root")],
        work_packages=work_packages,
        page_size=5,
    )
    project = Project(name="brain project")
    await service._ingestion._projects.create(project)

    result = await service.bootstrap(project_id=project.id, external_project_id="8")
    assert result.status == BootstrapStatus.READY
    assert result.work_items_ingested == 12
    assert result.pages_fetched == 3  # 5 + 5 + 2

    # No duplicates.
    stored = await service._ingestion._work_items.list_by_project(project.id)
    assert len(stored) == 12
    assert len({w.id for w in stored}) == 12


async def test_gate_bootstrap_is_idempotent_on_rerun() -> None:
    work_packages = [_work_item("1", summary="task-1"), _work_item("2", summary="task-2")]
    service, provider, _, _ = _service_and_provider(
        projects=[_project("8", "Root")],
        work_packages=work_packages,
    )
    project = Project(name="brain project")
    await service._ingestion._projects.create(project)

    first = await service.bootstrap(project_id=project.id, external_project_id="8")
    second = await service.bootstrap(project_id=project.id, external_project_id="8")
    assert first.status == BootstrapStatus.READY
    # A completed bootstrap is reported as already-ready without re-fetching.
    assert second.status == BootstrapStatus.READY
    assert second.resumed is True
    assert provider.project_fetches == 1

    stored = await service._ingestion._work_items.list_by_project(project.id)
    assert len(stored) == 2


async def test_gate_bootstrap_force_rerun_reconciles() -> None:
    service, provider, _, _ = _service_and_provider(
        projects=[_project("8", "Root")],
        work_packages=[_work_item("1", summary="task-1")],
    )
    project = Project(name="brain project")
    await service._ingestion._projects.create(project)

    await service.bootstrap(project_id=project.id, external_project_id="8")
    forced = await service.bootstrap(project_id=project.id, external_project_id="8", force=True)
    assert forced.status == BootstrapStatus.READY
    assert provider.project_fetches == 2
    stored = await service._ingestion._work_items.list_by_project(project.id)
    assert len(stored) == 1


async def test_gate_historical_assignment_triggers_nothing() -> None:
    """An existing task already assigned to the Brain must not run."""
    service, provider, events, _ = _service_and_provider(
        projects=[_project("8", "Root")],
        work_packages=[_work_item("43", summary="old", assignee_id="6")],
        brain_actor_id="6",
    )
    project = Project(name="brain project")
    await service._ingestion._projects.create(project)

    result = await service.bootstrap(project_id=project.id, external_project_id="8")
    assert result.status == BootstrapStatus.READY
    # BOOTSTRAP mode: no WorkItemAssigned, no RUN_WORK_ITEM, no events at all.
    assert events.published == []
    work_item = await service._ingestion._work_items.find_by_external_ref(
        "openproject", "43", "work_package"
    )
    assert work_item is not None
    assert work_item.assignee is not None


async def test_gate_historical_comments_are_context_only() -> None:
    service, provider, events, graph = _service_and_provider(
        projects=[_project("8", "Root")],
        work_packages=[_work_item("43", summary="t")],
        activities={
            "43": [
                _activity("c-1", "historical note"),
                _activity("c-2", "another note"),
            ]
        },
    )
    project = Project(name="brain project")
    await service._ingestion._projects.create(project)

    result = await service.bootstrap(project_id=project.id, external_project_id="8")
    assert result.comments_ingested == 2
    # NO HumanFeedbackReceived for historical comments.
    assert events.published == []
    work_item = await service._ingestion._work_items.find_by_external_ref(
        "openproject", "43", "work_package"
    )
    assert work_item is not None
    comments = await service._ingestion._comments.list_by_work_item(work_item.id)
    assert len(comments) == 2
    assert all(c.kind.value == "context" for c in comments)

    # A NEW comment after bootstrap is feedback (live mode).
    await service._ingestion.ingest_comment(
        work_item_id=work_item.id,
        external_id="c-3",
        author_name="alice",
        text="new question",
        mode=IngestionMode.LIVE,
    )
    assert any(event.event_type.value == "human_feedback_received" for event in events.published)


async def test_gate_bootstrap_establishes_watermark() -> None:
    service, provider, _, _ = _service_and_provider(
        projects=[_project("8", "Root")],
        work_packages=[_work_item("43", summary="t")],
    )
    project = Project(name="brain project")
    await service._ingestion._projects.create(project)

    await service.bootstrap(project_id=project.id, external_project_id="8")
    watermark = await service._watermarks.get_or_create("openproject", "work_items:8")
    assert watermark.bootstrap_completed_at is not None
    assert watermark.last_external_id == "43"
    # Durable baseline snapshots exist for diffing.
    snapshot = await service._ingestion._snapshots.get("43")
    assert snapshot is not None


async def test_gate_bootstrap_parent_resolution_two_pass() -> None:
    """Parent arriving after the child is resolved in pass 2."""
    work_packages = [
        _work_item("43", summary="child", parent_id=21),
        _work_item("21", summary="parent"),
    ]
    service, provider, _, _ = _service_and_provider(
        projects=[_project("8", "Root")],
        work_packages=work_packages,
    )
    project = Project(name="brain project")
    await service._ingestion._projects.create(project)

    result = await service.bootstrap(project_id=project.id, external_project_id="8")
    assert result.status == BootstrapStatus.READY
    child = await service._ingestion._work_items.find_by_external_ref(
        "openproject", "43", "work_package"
    )
    parent = await service._ingestion._work_items.find_by_external_ref(
        "openproject", "21", "work_package"
    )
    assert child is not None and parent is not None
    assert child.parent_id == parent.id


async def test_gate_bootstrap_resumes_from_checkpoint() -> None:
    """An interrupted bootstrap resumes from its last page."""
    work_packages = [_work_item(str(i), summary=f"task-{i}") for i in range(1, 11)]
    service, provider, _, _ = _service_and_provider(
        projects=[_project("8", "Root")],
        work_packages=work_packages,
        page_size=5,
    )
    project = Project(name="brain project")
    await service._ingestion._projects.create(project)

    # First run fails after page 1 (checkpoint at page 1).
    calls = {"n": 0}

    class _FlakyProvider:
        async def list_projects(self):
            return provider._projects

        async def list_work_packages(self, project_external_id, *, offset=1, page_size=100):
            del offset, page_size
            calls["n"] += 1
            if calls["n"] == 1:
                return provider._work_packages[0:5]
            raise RuntimeError("provider boom")

        async def list_activities(self, work_package_external_id):
            return []

    service._provider = _FlakyProvider()  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        await service.bootstrap(project_id=project.id, external_project_id="8")

    state = await service._bootstrap_states.get(project.id, "openproject")
    assert state is not None
    assert state.status == BootstrapStatus.FAILED
    assert state.last_error is not None

    # Resume: provider works again; only remaining pages are fetched.
    service._provider = provider
    result = await service.bootstrap(project_id=project.id, external_project_id="8")
    assert result.status == BootstrapStatus.READY
    assert result.resumed is False
    stored = await service._ingestion._work_items.list_by_project(project.id)
    assert len(stored) == 10


# --- adapter-level normalization (Phase 2.3) -------------------------------


class _FakeTransport:
    """Fake OpenProjectTransport with the bootstrap surface."""

    def __init__(self) -> None:
        self.project_payloads = [
            {
                "id": 8,
                "name": "Root",
                "identifier": "root",
                "active": True,
                "_embedded": {},
            },
            {
                "id": 9,
                "name": "Sub",
                "identifier": "sub",
                "active": True,
                "_embedded": {"parent": {"id": 8, "name": "Root"}},
            },
        ]
        self.work_package_payloads = [
            {
                "id": 43,
                "subject": "Fix login",
                "description": {"raw": "desc"},
                "_embedded": {
                    "type": {"name": "Task"},
                    "priority": {"name": "High"},
                    "status": {"name": "In progress"},
                    "project": {"id": 8, "name": "Root"},
                    "assignee": {"id": 6, "name": "alice"},
                },
                "_links": {},
            }
        ]
        self.activity_payloads = [
            {
                "id": 1,
                "createdAt": "2026-01-01T10:00:00Z",
                "_embedded": {
                    "comment": {"raw": "Please clarify."},
                    "author": {"id": 6, "name": "alice"},
                },
            }
        ]

    async def list_projects(self) -> list[dict[str, object]]:
        return self.project_payloads

    async def list_project_work_packages(
        self,
        project_external_id: str,
        *,
        offset: int = 1,
        page_size: int = 100,
    ) -> list[dict[str, object]]:
        del project_external_id, offset, page_size
        return self.work_package_payloads

    async def get_activities(self, external_id: str) -> list[dict[str, object]]:
        del external_id
        return self.activity_payloads

    async def get_work_package(self, external_id: str) -> dict[str, object]:  # pragma: no cover
        raise NotImplementedError

    async def list_updated_work_packages(
        self, since: object
    ) -> list[dict[str, object]]:  # pragma: no cover
        raise NotImplementedError

    async def create_work_package(
        self, payload: dict[str, object]
    ) -> dict[str, object]:  # pragma: no cover
        raise NotImplementedError

    async def update_status(self, external_id: str, status: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def post_comment(self, external_id: str, body: str) -> object:  # pragma: no cover
        raise NotImplementedError

    async def link_pull_request(self, external_id: str, pr_ref: str) -> None:  # pragma: no cover
        raise NotImplementedError


async def test_gate_adapter_bootstrap_surface_normalizes_payloads() -> None:
    import uuid

    from brain.adapters.work_management.openproject import OpenProjectAdapter
    from brain.domain.identity import ProjectId

    adapter = OpenProjectAdapter(
        transport=_FakeTransport(),
        project_id=ProjectId(uuid.uuid4()),
    )
    projects = await adapter.list_projects()
    assert len(projects) == 2
    assert projects[0].external_id == "8"
    assert projects[1].parent_external_id == "8"

    snapshots = await adapter.list_work_packages("8")
    assert len(snapshots) == 1
    assert snapshots[0].external_id == "43"
    assert snapshots[0].summary == "Fix login"
    assert snapshots[0].state == "In progress"
    assert snapshots[0].assignee_id == "6"
    assert snapshots[0].priority == "High"

    activities = await adapter.list_activities("43")
    assert len(activities) == 1
    assert activities[0].text == "Please clarify."
    assert activities[0].author_name == "alice"
