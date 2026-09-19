"""Work-management sync service (Phase 14).

Normalizes provider webhooks into canonical events (Task 14.3), persists
integration mappings (Task 14.4), and detects sync conflicts without
overwriting either side (Task 14.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from brain.application.openproject_ingestion import (
    IngestionMode,
    OpenProjectIngestionService,
)
from brain.domain.event_types import WorkItemChanged, model_to_envelope
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ProjectId, WorkItemId
from brain.domain.projects import Project
from brain.domain.sync_watermark import ProviderSyncWatermark
from brain.domain.work_items import WorkItem
from brain.domain.work_management import (
    IntegrationMapping,
    SyncConflict,
    SyncState,
)
from brain.ports.event_bus import EventBus
from brain.ports.repositories import ProjectRepository, WorkItemRepository
from brain.ports.sync_watermark import SyncWatermarkRepository
from brain.ports.work_management import WorkManagementPort
from brain.ports.work_management_bootstrap import WorkManagementBootstrapPort
from brain.ports.work_management_repo import WorkManagementIntegrationRepository


@dataclass
class WebhookNormalizationResult:
    work_item: WorkItem
    changed: bool
    conflict: SyncConflict | None = None


@dataclass
class SyncResult:
    work_item_id: WorkItemId
    mappings: list[IntegrationMapping] = field(default_factory=list)
    conflicts: list[SyncConflict] = field(default_factory=list)


class WorkManagementSyncService:
    """Keeps the brain's canonical work items in sync with a provider."""

    def __init__(
        self,
        *,
        provider: WorkManagementPort,
        integrations: WorkManagementIntegrationRepository,
        event_bus: EventBus,
    ) -> None:
        self._provider = provider
        self._integrations = integrations
        self._event_bus = event_bus

    async def normalize_webhook(
        self, external_id: str, raw: dict[str, object]
    ) -> WebhookNormalizationResult:
        """Normalize a provider webhook payload into a canonical WorkItem (14.3)."""
        ref = ExternalReference(
            provider=_provider_name(self._provider),
            external_id=external_id,
            external_type="work_package",
        )
        # Use the adapter's fetch to normalize provider fields canonically.
        work_item = await self._provider.fetch_work_item(ref)
        changed = bool(raw)
        return WebhookNormalizationResult(work_item=work_item, changed=changed)

    async def sync_from_provider(
        self, work_item_id: WorkItemId, external_id: str, since: datetime | None = None
    ) -> SyncResult:
        del since
        provider_work_item = await self._provider.fetch_work_item(
            ExternalReference(provider=_provider_name(self._provider), external_id=external_id)
        )
        mappings = await self._integrations.list_mappings(work_item_id)
        if not mappings:
            mapping = IntegrationMapping(
                work_item_id=work_item_id,
                provider=_provider_name(self._provider),
                external_id=external_id,
                sync_state=SyncState.SYNCED,
                last_synced_at=datetime.now(UTC),
            )
            await self._integrations.save_mapping(mapping)
            mappings = [mapping]

        conflicts: list[SyncConflict] = []
        # Provider status vs brain verification status may disagree; record it.
        provider_status = str(provider_work_item.human_work_status.value)
        if provider_status in {"done", "closed"}:
            conflict = SyncConflict(
                work_item_id=work_item_id,
                provider=_provider_name(self._provider),
                external_id=external_id,
                provider_field="status",
                provider_value=provider_status,
                brain_value="verification_pending",
            )
            await self._integrations.save_conflict(conflict)
            conflicts.append(conflict)

        return SyncResult(work_item_id=work_item_id, mappings=mappings, conflicts=conflicts)

    async def publish_work_item(self, work_item: WorkItem) -> IntegrationMapping:
        ref = await self._provider.publish_work_item(work_item)
        mapping = IntegrationMapping(
            work_item_id=work_item.id,
            provider=ref.provider,
            external_id=ref.external_id,
            sync_state=SyncState.SYNCED,
            last_synced_at=datetime.now(UTC),
        )
        await self._integrations.save_mapping(mapping)
        await self._event_bus.publish(
            model_to_envelope(
                WorkItemChanged(work_item=work_item),
                source=_provider_name(self._provider),
            )
        )
        return mapping


def _provider_name(provider: WorkManagementPort) -> str:
    mapping = getattr(provider, "_mapping", None)
    return mapping.provider if mapping is not None else "unknown"


# --- Pull reconciliation (Phase 3) -----------------------------------------


@dataclass
class PullSyncResult:
    project_id: ProjectId | None = None
    status: str = "ok"
    items_pulled: int = 0
    items_created: int = 0
    items_swept: int = 0
    pages_fetched: int = 0
    details: list[str] = field(default_factory=list)


class WorkManagementPullSyncService:
    """Periodic pull reconciliation for work management (Phase 3).

    The scheduler (or a manual trigger) asks the provider for work packages
    updated since the durable watermark, ingests each through the unified
    ingestion service in LIVE mode, then advances the watermark.  Unchanged
    snapshots diff to no-ops (no events).  After bootstrap, the first pull
    starts with a small overlap so changes that happened while bootstrap was
    running are not lost (doc Phase 9).

    A bounded missed-package sweep fetches previously-mapped work items that
    did not appear in the updated-since window (provider items whose
    ``updatedAt`` was not bumped, e.g. status-only changes done by the brain).
    """

    _OVERLAP_SECONDS = 5

    def __init__(
        self,
        *,
        provider: WorkManagementBootstrapPort,
        ingestion: OpenProjectIngestionService,
        projects: ProjectRepository,
        work_items: WorkItemRepository,
        integrations: WorkManagementIntegrationRepository,
        watermarks: SyncWatermarkRepository,
        page_size: int = 100,
        since_days: int = 1,
        sweep_limit: int = 20,
    ) -> None:
        self._provider = provider
        self._ingestion = ingestion
        self._projects = projects
        self._work_items = work_items
        self._integrations = integrations
        self._watermarks = watermarks
        self._page_size = page_size
        self._since_days = since_days
        self._sweep_limit = sweep_limit

    async def sync_project(self, project: Project) -> PullSyncResult:
        """Pull changed work packages for one project and advance its cursor."""
        ref = _provider_project_ref(project)
        if ref is None:
            return PullSyncResult(project_id=project.id, status="no_provider_ref")

        result = PullSyncResult(project_id=project.id, status="ok")
        watermark = await self._watermarks.get_or_create(
            "openproject", f"work_items:{ref.external_id}"
        )
        since = self._since(watermark)

        seen: list[str] = []
        offset = 1
        while True:
            page = await self._provider.list_changed_work_packages(
                since,
                offset=offset,
                page_size=self._page_size,
            )
            result.pages_fetched += 1
            for snapshot in page:
                ingested = await self._ingestion.ingest_work_item_snapshot(
                    snapshot,
                    mode=IngestionMode.LIVE,
                    source="pull",
                    project_id=project.id,
                    publish_unchanged=False,
                )
                seen.append(snapshot.external_id)
                if ingested.created:
                    result.items_created += 1
            result.items_pulled += len(page)
            result.details.append(f"page {offset}: {len(page)} work packages")
            if len(page) < self._page_size:
                break
            offset += self._page_size

        # Bounded sweep for previously-mapped items missing from the window.
        if watermark.last_synced_at is not None:
            result.items_swept = await self._sweep_missing(project, seen)

        # Advance the watermark only after the batch was processed (the
        # ingestion path is idempotent, so at-least-once delivery is safe).
        await self._watermarks.save(
            watermark.model_copy(
                update={
                    "last_synced_at": datetime.now(UTC),
                    "last_external_id": seen[-1] if seen else watermark.last_external_id,
                }
            )
        )
        result.details.append(f"watermark advanced; {result.items_pulled} pulled")
        return result

    def _since(self, watermark: ProviderSyncWatermark) -> datetime:
        now = datetime.now(UTC)
        if watermark.last_synced_at is not None:
            return watermark.last_synced_at
        if watermark.bootstrap_completed_at is not None:
            # Overlap: catch changes made while bootstrap was running.
            return watermark.bootstrap_completed_at - timedelta(seconds=self._OVERLAP_SECONDS)
        return now - timedelta(days=self._since_days)

    async def _sweep_missing(
        self,
        project: Project,
        seen: list[str],
    ) -> int:
        swept = 0
        for work_item in await self._work_items.list_by_project(project.id):
            if swept >= self._sweep_limit:
                break
            ref = _work_item_provider_ref(work_item)
            if ref is None or ref.external_id in seen:
                continue
            snapshot = await self._provider.get_work_package_snapshot(ref.external_id)
            if snapshot is None:
                continue
            await self._ingestion.ingest_work_item_snapshot(
                snapshot,
                mode=IngestionMode.LIVE,
                source="pull.sweep",
                project_id=project.id,
                publish_unchanged=False,
            )
            swept += 1
        return swept


def _provider_project_ref(project: Project) -> ExternalReference | None:
    for ref in project.external_refs:
        if ref.provider == "openproject" and ref.external_type == "project":
            return ref
    return None


def _work_item_provider_ref(work_item: WorkItem) -> ExternalReference | None:
    for ref in work_item.external_refs:
        if ref.provider == "openproject" and ref.external_type == "work_package":
            return ref
    return None


__all__ = [
    "PullSyncResult",
    "SyncResult",
    "WebhookNormalizationResult",
    "WorkManagementPullSyncService",
    "WorkManagementSyncService",
]
