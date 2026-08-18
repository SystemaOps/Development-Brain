"""System routes (Phase 23)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.schemas import AcceptedResult
from brain.bootstrap.container import BrainContainer

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
    del request
    # Phase 24+ enqueues a ReconcileProjectCommand; for now it is accepted.
    return AcceptedResult(command_id="reconcile")
