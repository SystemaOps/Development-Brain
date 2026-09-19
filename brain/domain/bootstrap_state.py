"""Provider bootstrap state domain model.

Durable progress of an existing-provider bootstrap import.  The lifecycle runs
CONNECTED -> DISCOVERING -> INGESTING -> BUILDING_GRAPH ->
ESTABLISHING_BASELINE -> READY -> LIVE_SYNC; the current stage and page cursor
let an interrupted bootstrap resume from its last checkpoint instead of
re-importing everything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import ProjectId


class BootstrapStatus(StrEnum):
    CONNECTED = "connected"
    DISCOVERING = "discovering"
    INGESTING = "ingesting"
    BUILDING_GRAPH = "building_graph"
    ESTABLISHING_BASELINE = "establishing_baseline"
    READY = "ready"
    LIVE_SYNC = "live_sync"
    FAILED = "failed"


class BootstrapStage(StrEnum):
    DISCOVER_PROJECTS = "discover_projects"
    FETCH_WORK_ITEMS = "fetch_work_items"
    RESOLVE_RELATIONS = "resolve_relations"
    INGEST_COMMENTS = "ingest_comments"
    INGEST_ATTACHMENTS = "ingest_attachments"
    BUILD_GRAPH = "build_graph"
    ESTABLISH_BASELINE = "establish_baseline"
    COMPLETE = "complete"


class ProviderBootstrapState(BaseModel):
    project_id: ProjectId
    provider: str
    status: BootstrapStatus = BootstrapStatus.CONNECTED
    stage: BootstrapStage = BootstrapStage.DISCOVER_PROJECTS
    last_page: int = 0
    items_processed: int = 0
    last_error: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


__all__ = ["BootstrapStage", "BootstrapStatus", "ProviderBootstrapState"]
