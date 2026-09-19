"""Phase 4 gate tests: full-chain ingestion scenarios against the runtime.

Proves the complete event->command flow for pull-discovered assignments:

    pull sync command -> pull service -> ingestion (LIVE) ->
    WorkItemAssigned -> handler -> RUN_WORK_ITEM queued

and that webhook + pull converge on the same canonical state in the real
container wiring.
"""

from __future__ import annotations

import pytest

from brain.application.openproject_parser import OpenProjectWorkItemSnapshot
from brain.application.work_management_sync import WorkManagementPullSyncService
from brain.bootstrap.container import create_brain_container
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
from brain.domain.external_reference import ExternalReference
from brain.domain.projects import Project
from brain.workers.loop import run_worker_once
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


def _settings(brain_actor_id: str | None = None) -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
        storage_semantic=WeaviateSettings(host="localhost"),
        storage_queue=RedisSettings(url="redis://localhost:6379/0", provider="inmemory"),
        work_management=WorkManagementSettings(
            enabled=True,
            provider="openproject",
            brain_actor_id=brain_actor_id or "",
            sync_enabled=True,
        ),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
    )


class _FakeChangedProvider:
    def __init__(self, snapshots: list[OpenProjectWorkItemSnapshot]) -> None:
        self._snapshots = snapshots

    async def list_changed_work_packages(self, since, *, offset=1, page_size=100):
        del since, offset, page_size
        return self._snapshots

    async def get_work_package_snapshot(self, external_id):
        return None

    async def list_projects(self):
        return []

    async def list_work_packages(self, project_external_id, *, offset=1, page_size=100):
        return []

    async def list_activities(self, work_package_external_id):
        return []


class _FakeWorkManagement:
    pass


async def test_gate_pull_assignment_triggers_run_command() -> None:
    """A pull-discovered assignment flows to RUN_WORK_ITEM via the handler."""
    container = await create_brain_container(_settings(brain_actor_id="6"))
    try:
        project = Project(
            name="pull-project",
            external_refs=[
                ExternalReference(provider="openproject", external_id="8", external_type="project")
            ],
        )
        await container.repositories.projects.create(project)

        snapshot = OpenProjectWorkItemSnapshot(
            external_id="43",
            summary="new task",
            state="In progress",
            project_id="8",
            assignee_id="6",
            assignee_name="brain",
        )
        provider = _FakeChangedProvider([snapshot])
        ingestion = container.services["openproject_ingestion"]
        pull = WorkManagementPullSyncService(
            provider=provider,  # type: ignore[arg-type]
            ingestion=ingestion,  # type: ignore[arg-type]
            projects=container.repositories.projects,
            work_items=container.repositories.work_items,
            integrations=container.repositories.work_management_integrations,
            watermarks=container.repositories.sync_watermarks,
        )
        container.services["openproject_pull_sync"] = pull  # type: ignore[attr-defined]
        container.work_management = _FakeWorkManagement()  # type: ignore[attr-defined]

        # Run the pull through the real command path.
        from brain.domain.commands import CommandType, SyncWorkManagementCommand, make_command
        from brain.ports.commands import CommandQueue

        queue = container.services["command_queue"]
        assert isinstance(queue, CommandQueue)
        await queue.enqueue(
            make_command(
                CommandType.SYNC_WORK_MANAGEMENT,
                SyncWorkManagementCommand(project_id=project.id),
            )
        )
        processed = await run_worker_once(container, max_commands=1)
        assert processed == 1

        # The work item was ingested canonically.
        work_item = await container.repositories.work_items.find_by_external_ref(
            "openproject", "43", "work_package"
        )
        assert work_item is not None
        assert work_item.title == "new task"

        # WorkItemAssigned reached the bus and the handler enqueued RUN_WORK_ITEM.
        bus = container.services["events"]
        from brain.adapters.in_memory.event_bus import InMemoryEventBus

        assert isinstance(bus, InMemoryEventBus)
        assert any(event.event_type.value == "work_item_assigned" for event in bus.published)
        assert await queue.pending_count() >= 1
    finally:
        await container.close()


async def test_gate_webhook_and_pull_same_container_state() -> None:
    """Webhook and pull paths converge on one canonical work item."""
    container = await create_brain_container(_settings(brain_actor_id="6"))
    try:
        project = Project(
            name="converge-project",
            external_refs=[
                ExternalReference(provider="openproject", external_id="8", external_type="project")
            ],
        )
        await container.repositories.projects.create(project)

        ingestion = container.services["openproject_ingestion"]
        from brain.application.openproject_ingestion import (
            IngestionMode,
            OpenProjectIngestionService,
        )

        assert isinstance(ingestion, OpenProjectIngestionService)
        await ingestion.ingest_work_item_snapshot(
            OpenProjectWorkItemSnapshot(
                external_id="43",
                summary="task",
                state="In progress",
                project_id="8",
            ),
            mode=IngestionMode.LIVE,
            source="webhook",
            project_id=project.id,
            provider_action="work_package:created",
        )
        await ingestion.ingest_work_item_snapshot(
            OpenProjectWorkItemSnapshot(
                external_id="43",
                summary="task",
                state="In progress",
                project_id="8",
            ),
            mode=IngestionMode.LIVE,
            source="pull",
            project_id=project.id,
            publish_unchanged=False,
        )

        work_items = await container.repositories.work_items.list_by_project(project.id)
        assert len(work_items) == 1
        assert work_items[0].title == "task"
    finally:
        await container.close()
