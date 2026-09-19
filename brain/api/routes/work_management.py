"""Work-management routes (Phase 3).

Manual pull-sync trigger: ``POST /api/v1/work-management/sync`` enqueues a
``SYNC_WORK_MANAGEMENT`` command so long-running provider pulls never block the
API (BOTH trigger: humans and schedulers converge on the same command).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.commands import enqueue_command
from brain.api.dependencies import get_container
from brain.api.errors import BrainAPIError
from brain.bootstrap.container import BrainContainer
from brain.domain.commands import CommandType, SyncWorkManagementCommand
from brain.domain.identity import ProjectId

router = APIRouter()


@router.post("/api/v1/work-management/sync", status_code=202)
async def sync_work_management(request: Request) -> dict[str, object]:
    """Enqueue a provider pull for one project (BOTH trigger)."""
    body = await request.json()
    project_id = body.get("project_id")
    if not project_id:
        raise BrainAPIError("invalid_request", "project_id is required", status_code=422)
    container: BrainContainer = get_container(request)
    project = await container.repositories.projects.get(ProjectId(uuid.UUID(str(project_id))))
    if project is None:
        raise BrainAPIError("not_found", "project not found", status_code=404)
    result = await enqueue_command(
        container,
        CommandType.SYNC_WORK_MANAGEMENT,
        SyncWorkManagementCommand(project_id=project.id),
        correlation_id=request.state.correlation_id,
    )
    return result.model_dump(mode="json")


__all__ = ["router"]
