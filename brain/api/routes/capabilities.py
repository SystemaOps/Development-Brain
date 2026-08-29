"""Capability route (Phase 23)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.bootstrap.container import BrainContainer

router = APIRouter()


@router.get("/api/v1/capabilities")
async def capabilities(request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    registry = container.capability_registry()
    return {
        name: {
            "status": descriptor.health.status.value,
            "provider": descriptor.provider,
            "required": descriptor.required,
            "detail": descriptor.health.detail,
        }
        for name, descriptor in registry.snapshot().items()
    }
