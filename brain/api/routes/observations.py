"""Observation routes (Phase 23/26).

The engineering journal API: list/search observations, acknowledge, resolve,
and receive human feedback.  Phase 26 wires these to the canonical
ObservationService.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.errors import BrainAPIError
from brain.application.observations import ObservationService
from brain.bootstrap.container import BrainContainer
from brain.domain.identity import ObservationId, ProjectId, WorkItemId

router = APIRouter()


def _service(request: Request) -> ObservationService:
    container: BrainContainer = get_container(request)
    service = container.services["observations"]
    assert isinstance(service, ObservationService)
    return service


@router.get("/api/v1/observations")
async def list_observations(
    request: Request,
    project_id: uuid.UUID | None = None,
    work_item_id: uuid.UUID | None = None,
) -> dict[str, object]:
    service = _service(request)
    if work_item_id is not None:
        observations = await service.list_by_work_item(WorkItemId(work_item_id))
    elif project_id is not None:
        observations = await service.list_by_project(ProjectId(project_id))
    else:
        observations = await service.list_recent()
    return {"observations": [o.model_dump(mode="json") for o in observations]}


@router.get("/api/v1/work-items/{work_item_id}/observations")
async def work_item_observations(work_item_id: uuid.UUID, request: Request) -> dict[str, object]:
    service = _service(request)
    observations = await service.list_by_work_item(WorkItemId(work_item_id))
    return {
        "work_item_id": str(work_item_id),
        "observations": [o.model_dump(mode="json") for o in observations],
    }


@router.post("/api/v1/observations/{observation_id}/acknowledge")
async def acknowledge_observation(observation_id: uuid.UUID, request: Request) -> dict[str, object]:
    service = _service(request)
    observation = await service.acknowledge(
        ObservationId(observation_id),
        correlation_id=request.state.correlation_id,
    )
    if observation is None:
        raise BrainAPIError("not_found", "observation not found", status_code=404)
    return {"status": "acknowledged", "observation": observation.model_dump(mode="json")}


@router.post("/api/v1/observations/{observation_id}/resolve")
async def resolve_observation(observation_id: uuid.UUID, request: Request) -> dict[str, object]:
    service = _service(request)
    observation = await service.resolve(
        ObservationId(observation_id),
        correlation_id=request.state.correlation_id,
    )
    if observation is None:
        raise BrainAPIError("not_found", "observation not found", status_code=404)
    return {"status": "resolved", "observation": observation.model_dump(mode="json")}


@router.post("/api/v1/work-items/{work_item_id}/feedback")
async def work_item_feedback(work_item_id: uuid.UUID, request: Request) -> dict[str, object]:
    del work_item_id, request
    return {"status": "received"}
