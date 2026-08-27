"""System routes (Phase 23)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from brain.api.commands import enqueue_command
from brain.api.dependencies import get_container
from brain.api.schemas import AcceptedResult
from brain.bootstrap.container import BrainContainer
from brain.domain.commands import CommandType

router = APIRouter()


@router.get("/api/v1/system/status")
async def system_status(request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    return {
        "environment": container.settings.runtime.environment,
        "ready": container.is_ready(),
        "problems": container.ready_problems(),
        "executors": [d.name for d in container.executor_descriptors],
        "capabilities": container.capabilities(),
    }


@router.get("/api/v1/system/version")
async def system_version() -> dict[str, str]:
    return {"version": "0.1.0", "build": "dev"}


@router.post("/api/v1/system/reconcile", response_model=AcceptedResult, status_code=202)
async def system_reconcile(request: Request) -> AcceptedResult:
    container: BrainContainer = get_container(request)
    # Global reconciliation enqueues a command; projects resolve later.
    from brain.domain.commands import ReconcileProjectCommand
    from brain.domain.identity import ProjectId

    project = await container.repositories.projects.list()
    if not project:
        return AcceptedResult(command_id="reconcile-none")
    return await enqueue_command(
        container,
        CommandType.RECONCILE_PROJECT,
        ReconcileProjectCommand(project_id=ProjectId(project[0].id)),
        correlation_id=request.state.correlation_id,
    )
