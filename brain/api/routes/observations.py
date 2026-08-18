"""Observation routes (Phase 23).

Thin until Phase 26 introduces the engineering journal; the routes are defined
so the API surface is stable and returns canonical empty results.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/v1/observations")
async def list_observations(request: Request) -> dict[str, object]:
    del request
    return {"observations": []}


@router.post("/api/v1/observations/{observation_id}/acknowledge")
async def acknowledge_observation(observation_id: uuid.UUID, request: Request) -> dict[str, object]:
    del observation_id, request
    return {"status": "acknowledged"}


@router.post("/api/v1/observations/{observation_id}/resolve")
async def resolve_observation(observation_id: uuid.UUID, request: Request) -> dict[str, object]:
    del observation_id, request
    return {"status": "resolved"}


@router.post("/api/v1/work-items/{work_item_id}/feedback")
async def work_item_feedback(work_item_id: uuid.UUID, request: Request) -> dict[str, object]:
    del work_item_id, request
    return {"status": "received"}
