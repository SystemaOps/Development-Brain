"""Health routes (Phase 23).

``/health/live`` reports the process is alive; ``/health/ready`` reports
whether required Brain capabilities are available.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from brain.api.dependencies import get_container
from brain.bootstrap.container import BrainContainer

router = APIRouter()


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    container: BrainContainer = get_container(request)
    if container.is_ready():
        return JSONResponse({"status": "ready"})
    return JSONResponse(
        {"status": "not_ready", "problems": container.ready_problems()},
        status_code=503,
    )
