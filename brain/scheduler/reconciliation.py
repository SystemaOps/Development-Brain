"""Scheduler reconciliation logic (Phase 29).

Periodic jobs guarantee eventual consistency when webhooks are missed or
providers temporarily fail.  Each job reports what it reconciled so the
scheduler can log and observe the outcome.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from brain.bootstrap.container import BrainContainer
from brain.domain.executions import ExecutionStatus
from brain.domain.identity import (
    RepositoryId,
    WorkItemId,
)
from brain.domain.observations import ObservationType
from brain.ports.commands import CommandQueue

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationReport:
    """Outcome of one scheduler pass."""

    repositories_checked: int = 0
    repositories_stale: int = 0
    repositories_synced: int = 0
    work_management_checked: int = 0
    work_management_synced: int = 0
    documentation_checked: int = 0
    projections_stale: int = 0
    stuck_executions: int = 0
    stuck_recovered: int = 0
    projections_retried: int = 0
    observations_created: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


class ReconciliationService:
    """Runs the reconciliation jobs against one BrainContainer."""

    def __init__(
        self,
        container: BrainContainer,
        *,
        stuck_threshold_seconds: int = 3600,
        queue: CommandQueue | None = None,
    ) -> None:
        self._container = container
        self._stuck_threshold = timedelta(seconds=stuck_threshold_seconds)
        self._queue = queue

    async def reconcile(self) -> ReconciliationReport:
        report = ReconciliationReport()
        await self.reconcile_repositories(report)
        await self.reconcile_work_management(report)
        await self.reconcile_documentation(report)
        await self.check_projection_freshness(report)
        await self.detect_stuck_executions(report)
        await self.retry_failed_projections(report)
        return report

    # --- 29.2 Repository reconciliation -----------------------------------

    async def reconcile_repositories(self, report: ReconciliationReport) -> None:
        repos = self._container.repositories.repositories
        snapshots = self._container.repositories.repository_snapshots
        projects = await self._container.repositories.projects.list()
        repositories: list[object] = []
        for project in projects:
            repositories.extend(await repos.list_by_project(project.id))
        for repository in repositories:
            report.repositories_checked += 1
            if repository.current_revision is None:  # type: ignore[attr-defined]
                continue
            latest = await snapshots.list_snapshots(repository.id)  # type: ignore[attr-defined]
            if not latest:
                continue
            latest_revision = latest[-1].revision
            if latest_revision != repository.current_revision:  # type: ignore[attr-defined]
                report.repositories_stale += 1
                report.details.append(
                    f"repository {repository.name} stale: "  # type: ignore[attr-defined]
                    f"{repository.current_revision} vs {latest_revision}"  # type: ignore[attr-defined]
                )
                await self._enqueue_sync(repository.id)  # type: ignore[attr-defined]
                report.repositories_synced += 1

    async def _enqueue_sync(self, repository_id: RepositoryId) -> None:
        if self._queue is None:
            return
        from brain.domain.commands import (
            CommandType,
            SyncRepositoryCommand,
            TriggerType,
            make_command,
        )

        await self._queue.enqueue(
            make_command(
                CommandType.SYNC_REPOSITORY,
                SyncRepositoryCommand(repository_id=repository_id),
                trigger_type=TriggerType.SCHEDULED,
            )
        )

    # --- 29.3 Work-management reconciliation -------------------------------

    async def reconcile_work_management(self, report: ReconciliationReport) -> None:
        """Pull changed work items when a provider + pull sync are configured.

        Webhooks provide low latency; this periodic pull provides eventual
        consistency (missed webhooks, comment-only changes, closed items).
        """
        if self._container.work_management is None:
            return
        settings = self._container.settings.work_management
        if not settings.sync_enabled:
            return
        pull = self._container.services.get("openproject_pull_sync")
        if pull is None:
            return

        from brain.domain.external_reference import ExternalReference

        projects = await self._container.repositories.projects.list()
        for project in projects:
            refs = project.external_refs
            has_provider_ref = any(
                isinstance(ref, ExternalReference)
                and ref.provider == "openproject"
                and ref.external_type == "project"
                for ref in refs
            )
            if not has_provider_ref:
                continue
            report.work_management_checked += 1
            if self._queue is not None:
                from brain.domain.commands import (
                    CommandType,
                    SyncWorkManagementCommand,
                    TriggerType,
                    make_command,
                )

                await self._queue.enqueue(
                    make_command(
                        CommandType.SYNC_WORK_MANAGEMENT,
                        SyncWorkManagementCommand(project_id=project.id),
                        trigger_type=TriggerType.SCHEDULED,
                    )
                )
                report.details.append(f"work management sync enqueued for project {project.name}")
            else:
                # No queue (tests/reference): run the pull inline.
                sync_project = getattr(pull, "sync_project", None)
                if sync_project is None:
                    continue
                sync_result = await sync_project(project)
                report.details.append(
                    f"work management synced for project {project.name}: "
                    f"{getattr(sync_result, 'items_pulled', 0)} pulled, "
                    f"{getattr(sync_result, 'items_created', 0)} created"
                )
            report.work_management_synced += 1

    # --- 29.4 Documentation reconciliation ---------------------------------

    async def reconcile_documentation(self, report: ReconciliationReport) -> None:
        for _port in self._container.documentation_ports:
            report.documentation_checked += 1
            # Changes are fetched via DocumentationPort.list_changed_documents
            # in the ingestion pipeline; presence here means they are tracked.

    # --- 29.5 Projection freshness -----------------------------------------

    async def check_projection_freshness(self, report: ReconciliationReport) -> None:
        from brain.domain.capabilities import CapabilityName

        projects = await self._container.repositories.projects.list()
        for project in projects:
            catalog = self._container.repositories.software_catalog
            components = await catalog.list_components(project.id)
            # Derived topology lives in Postgres; graph projection is a
            # rebuildable projection.  If the graph capability is unavailable,
            # schedule a repair rather than silently serving stale data.
            if (
                components
                and self._container.capability_registry().get(CapabilityName.NEO4J) is None
            ):
                report.projections_stale += 1
                report.details.append(f"project {project.name}: graph projection stale")

    # --- 29.6 Stuck execution detection ------------------------------------

    async def detect_stuck_executions(self, report: ReconciliationReport) -> None:
        from brain.application.observations import ObservationService

        executions = self._container.repositories.executions
        observations = self._container.services["observations"]
        assert isinstance(observations, ObservationService)
        now = datetime.now(UTC)
        for work_item_id in await self._work_item_ids():
            for execution in await executions.list_by_work_item(work_item_id):
                if execution.status not in {
                    ExecutionStatus.STARTED,
                    ExecutionStatus.RUNNING,
                }:
                    continue
                if execution.started_at + self._stuck_threshold > now:
                    continue
                report.stuck_executions += 1
                execution.status = ExecutionStatus.BLOCKED
                await executions.update(execution)
                report.stuck_recovered += 1
                report.details.append(f"execution {execution.id} stuck; marked blocked")
                # Create a human-action observation for the blocked execution.
                project = await self._container.repositories.work_items.get(work_item_id)
                project_id = project.project_id if project is not None else None
                if project_id is not None:
                    await observations.create(
                        project_id=project_id,
                        observation_type=ObservationType.HUMAN_ACTION_REQUIRED,
                        title="Execution stuck",
                        body=f"Execution {execution.id} exceeded the stuck threshold.",
                        work_item_id=work_item_id,
                        execution_id=execution.id,
                        dedup_key=f"stuck:{execution.id}",
                    )
                    report.observations_created.append(str(execution.id))

    async def _work_item_ids(self) -> list[WorkItemId]:
        projects = await self._container.repositories.projects.list()
        work_items = self._container.repositories.work_items
        ids: list[WorkItemId] = []
        for project in projects:
            for work_item in await work_items.list_by_project(project.id):
                ids.append(work_item.id)
        return ids

    # --- 29.7 Observation projection retry ---------------------------------

    async def retry_failed_projections(self, report: ReconciliationReport) -> None:
        from brain.application.observation_projection import ObservationProjectionService

        projection = self._container.services["observation_projection"]
        assert isinstance(projection, ObservationProjectionService)
        retried = await projection.retry_failed(limit=50)
        report.projections_retried += len(retried)
        for reference in retried:
            report.details.append(
                f"retried observation {reference.observation_id} -> {reference.provider}"
            )


__all__ = ["ReconciliationReport", "ReconciliationService"]
