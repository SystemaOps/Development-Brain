"""OpenProject existing-project bootstrap service (Phase 2).

Imports a well-established OpenProject project into the brain before live
synchronization begins (``docs/data_ingestion/OPENPROJECT_EXISTING_PROJECT_BOOTSTRAP_PLAN.md``).

Lifecycle: CONNECTED -> DISCOVERING -> INGESTING -> BUILDING_GRAPH ->
ESTABLISHING_BASELINE -> READY -> LIVE_SYNC.

Bootstrap teaches the brain what already exists: projects, work items,
relations, comments and attachments are persisted canonically and projected
into the graph, durable snapshots form the diff baseline, and the sync
watermark records where incremental sync must resume.  Historical state never
triggers workflows — no ``WorkItemAssigned``, no ``RUN_WORK_ITEM``, no
``HumanFeedbackReceived`` for old comments (doc Phase 3/5).

The service is idempotent and resumable: progress is checkpointed in
``ProviderBootstrapState`` (stage + page) so an interrupted bootstrap resumes
from its last checkpoint instead of re-importing everything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from brain.application.openproject_ingestion import (
    IngestionMode,
    OpenProjectIngestionService,
)
from brain.application.openproject_parser import OpenProjectWorkItemSnapshot
from brain.domain.bootstrap_state import (
    BootstrapStage,
    BootstrapStatus,
    ProviderBootstrapState,
)
from brain.domain.identity import ProjectId
from brain.ports.bootstrap_state import BootstrapStateRepository
from brain.ports.sync_watermark import SyncWatermarkRepository
from brain.ports.work_management_bootstrap import (
    ProviderProject,
    WorkManagementBootstrapPort,
)

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 100


@dataclass
class BootstrapResult:
    project_id: ProjectId
    status: BootstrapStatus
    projects_ingested: int = 0
    work_items_ingested: int = 0
    comments_ingested: int = 0
    relations_ingested: int = 0
    pages_fetched: int = 0
    resumed: bool = False
    details: list[str] = field(default_factory=list)


class OpenProjectProjectBootstrapService:
    """Bootstraps one existing OpenProject project into the brain."""

    def __init__(
        self,
        *,
        provider: WorkManagementBootstrapPort,
        ingestion: OpenProjectIngestionService,
        bootstrap_states: BootstrapStateRepository,
        watermarks: SyncWatermarkRepository,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        self._provider = provider
        self._ingestion = ingestion
        self._bootstrap_states = bootstrap_states
        self._watermarks = watermarks
        self._page_size = page_size

    async def bootstrap(
        self,
        *,
        project_id: ProjectId,
        external_project_id: str,
        force: bool = False,
    ) -> BootstrapResult:
        """Run (or resume) the full bootstrap for one provider project."""
        state = await self._bootstrap_states.get(project_id, "openproject")
        if state is None:
            state = ProviderBootstrapState(project_id=project_id, provider="openproject")
            await self._bootstrap_states.save(state)

        if not force and state.status in {BootstrapStatus.READY, BootstrapStatus.LIVE_SYNC}:
            result = BootstrapResult(
                project_id=project_id,
                status=state.status,
                resumed=True,
                details=["bootstrap already completed; set force to re-run"],
            )
            return result

        result = BootstrapResult(project_id=project_id, status=BootstrapStatus.CONNECTED)
        try:
            # 1. Discover the project hierarchy (CONNECTED -> DISCOVERING).
            state = state.model_copy(
                update={
                    "status": BootstrapStatus.DISCOVERING,
                    "stage": BootstrapStage.DISCOVER_PROJECTS,
                    "last_error": None,
                }
            )
            await self._bootstrap_states.save(state)
            projects = await self._provider.list_projects()
            if not any(p.external_id == external_project_id for p in projects):
                return await self._fail_definitive(
                    state,
                    result,
                    f"provider project {external_project_id} does not exist or is not visible",
                )
            result.projects_ingested = await self._ingest_projects(
                projects, target_external_id=external_project_id, target_project_id=project_id
            )

            # 2. Fetch all existing work packages with pagination.
            state = state.model_copy(
                update={
                    "status": BootstrapStatus.INGESTING,
                    "stage": BootstrapStage.FETCH_WORK_ITEMS,
                }
            )
            await self._bootstrap_states.save(state)
            snapshots = await self._fetch_all_work_packages(
                external_project_id, state, result, project_id
            )

            # 3. Two-pass relationship resolution.
            state = state.model_copy(
                update={
                    "stage": BootstrapStage.RESOLVE_RELATIONS,
                }
            )
            await self._bootstrap_states.save(state)
            await self._ingestion.resolve_relationships(snapshots)
            relations = await self._count_relations(project_id)
            result.relations_ingested = relations

            # 4. Historical comments as context only.
            state = state.model_copy(
                update={
                    "stage": BootstrapStage.INGEST_COMMENTS,
                }
            )
            await self._bootstrap_states.save(state)
            result.comments_ingested = await self._ingest_comments(snapshots)

            # 5. Graph projection already happened per entity during
            #    ingestion (work-item subgraph + project nodes).
            state = state.model_copy(
                update={
                    "status": BootstrapStatus.BUILDING_GRAPH,
                    "stage": BootstrapStage.BUILD_GRAPH,
                }
            )
            await self._bootstrap_states.save(state)

            # 6. Establish durable baseline + sync watermark.
            state = state.model_copy(
                update={
                    "status": BootstrapStatus.ESTABLISHING_BASELINE,
                    "stage": BootstrapStage.ESTABLISH_BASELINE,
                }
            )
            await self._bootstrap_states.save(state)
            await self._establish_baseline(external_project_id, snapshots)

            # 7. READY -> LIVE_SYNC.
            completed_at = datetime.now(UTC)
            state = state.model_copy(
                update={
                    "status": BootstrapStatus.READY,
                    "stage": BootstrapStage.COMPLETE,
                    "completed_at": completed_at,
                    "last_error": None,
                }
            )
            await self._bootstrap_states.save(state)
            result.status = BootstrapStatus.READY
            result.details.append(
                f"bootstrap complete: {result.work_items_ingested} work items, "
                f"{result.comments_ingested} comments"
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("bootstrap failed for project %s", project_id)
            failed = state.model_copy(
                update={
                    "status": BootstrapStatus.FAILED,
                    "last_error": f"{type(exc).__name__}: {exc}",
                }
            )
            await self._bootstrap_states.save(failed)
            result.status = BootstrapStatus.FAILED
            result.details.append(f"bootstrap failed: {exc}")
            raise

    async def _fail_definitive(
        self,
        state: ProviderBootstrapState,
        result: BootstrapResult,
        message: str,
    ) -> BootstrapResult:
        """Mark the bootstrap FAILED with a definitive error (no retry).

        A provider project that does not exist will never succeed; failing
        with a clear status instead of raising keeps the worker from retrying
        the command forever.
        """
        failed = state.model_copy(
            update={
                "status": BootstrapStatus.FAILED,
                "last_error": message,
            }
        )
        await self._bootstrap_states.save(failed)
        result.status = BootstrapStatus.FAILED
        result.details.append(message)
        return result

    async def _ingest_projects(
        self,
        projects: list[ProviderProject],
        *,
        target_external_id: str,
        target_project_id: ProjectId,
    ) -> int:
        ingested = 0
        for project in projects:
            if project.external_id == target_external_id:
                # The provider project maps onto the brain project that owns
                # the bootstrap: the brain identity stays stable and all
                # imported work items land in it.
                await self._ingestion.upsert_project(
                    external_id=project.external_id,
                    name=project.name,
                    description=project.description,
                    parent_external_id=project.parent_external_id,
                    project_id=target_project_id,
                )
            else:
                await self._ingestion.upsert_project(
                    external_id=project.external_id,
                    name=project.name,
                    description=project.description,
                    parent_external_id=project.parent_external_id,
                )
            ingested += 1
        return ingested

    async def _fetch_all_work_packages(
        self,
        external_project_id: str,
        state: ProviderBootstrapState,
        result: BootstrapResult,
        project_id: ProjectId,
    ) -> list[OpenProjectWorkItemSnapshot]:
        snapshots: list[OpenProjectWorkItemSnapshot] = []
        offset = max(state.last_page, 1)
        while True:
            page = await self._provider.list_work_packages(
                external_project_id,
                offset=offset,
                page_size=self._page_size,
            )
            result.pages_fetched += 1
            for snapshot in page:
                await self._ingestion.ingest_work_item_snapshot(
                    snapshot,
                    mode=IngestionMode.BOOTSTRAP,
                    source="bootstrap",
                    project_id=project_id,
                )
                snapshots.append(snapshot)
            result.work_items_ingested += len(page)
            result.details.append(f"page {offset}: {len(page)} work packages")

            # Checkpoint progress for resume.
            state = state.model_copy(update={"last_page": offset})
            await self._bootstrap_states.save(state)

            if len(page) < self._page_size:
                break
            offset += self._page_size
        return snapshots

    async def _ingest_comments(self, snapshots: list[OpenProjectWorkItemSnapshot]) -> int:
        ingested = 0
        for snapshot in snapshots:
            work_item = await self._ingestion._work_items.find_by_external_ref(
                "openproject", snapshot.external_id, "work_package"
            )
            if work_item is None:
                continue
            activities = await self._provider.list_activities(snapshot.external_id)
            for activity in activities:
                if not activity.text.strip():
                    continue
                await self._ingestion.ingest_comment(
                    work_item_id=work_item.id,
                    external_id=activity.external_id,
                    author_name=activity.author_name,
                    text=activity.text,
                    mode=IngestionMode.BOOTSTRAP,
                    source="bootstrap",
                )
                ingested += 1
        return ingested

    async def _count_relations(self, project_id: ProjectId) -> int:
        count = 0
        for work_item in await self._ingestion._work_items.list_by_project(project_id):
            count += len(await self._ingestion._relations.list_by_work_item(work_item.id))
        return count

    async def _establish_baseline(
        self,
        external_project_id: str,
        snapshots: list[OpenProjectWorkItemSnapshot],
    ) -> None:
        # Durable snapshots were saved per ingestion (the diff baseline).
        watermark = await self._watermarks.get_or_create(
            "openproject", f"work_items:{external_project_id}"
        )
        watermark = watermark.model_copy(
            update={
                "last_synced_at": datetime.now(UTC),
                "bootstrap_completed_at": datetime.now(UTC),
                "last_external_id": snapshots[-1].external_id if snapshots else None,
            }
        )
        await self._watermarks.save(watermark)


__all__ = ["BootstrapResult", "OpenProjectProjectBootstrapService"]
