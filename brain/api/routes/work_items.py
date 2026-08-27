"""Work item routes (Phase 23)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.commands import enqueue_command
from brain.api.dependencies import get_container
from brain.api.errors import BrainAPIError
from brain.api.schemas import (
    AcceptedResult,
    WorkItemCreate,
    WorkItemRead,
    WorkItemUpdate,
)
from brain.bootstrap.container import BrainContainer
from brain.domain.commands import CommandType
from brain.domain.identity import ProjectId, WorkItemId
from brain.domain.work_items import WorkItem, WorkItemType

router = APIRouter()


def _to_read(work_item: WorkItem) -> WorkItemRead:
    return WorkItemRead(
        id=work_item.id,
        project_id=work_item.project_id,
        title=work_item.title,
        description=work_item.description,
        type=work_item.type.value,
        human_work_status=work_item.human_work_status.value,
        implementation_status=work_item.implementation_status.value,
        verification_status=work_item.verification_status.value,
        pull_request_status=work_item.pull_request_status.value,
    )


@router.post("/api/v1/work-items", response_model=WorkItemRead, status_code=201)
async def create_work_item(payload: WorkItemCreate, request: Request) -> WorkItemRead:
    container: BrainContainer = get_container(request)
    work_item = WorkItem(
        project_id=ProjectId(payload.project_id),
        title=payload.title,
        description=payload.description,
        type=WorkItemType(payload.type),
    )
    created = await container.repositories.work_items.create(work_item)
    return _to_read(created)


@router.get("/api/v1/work-items/{work_item_id}", response_model=WorkItemRead)
async def get_work_item(work_item_id: uuid.UUID, request: Request) -> WorkItemRead:
    container: BrainContainer = get_container(request)
    work_item = await container.repositories.work_items.get(WorkItemId(work_item_id))
    if work_item is None:
        raise BrainAPIError("not_found", "work item not found", status_code=404)
    return _to_read(work_item)


@router.patch("/api/v1/work-items/{work_item_id}", response_model=WorkItemRead)
async def update_work_item(
    work_item_id: uuid.UUID, payload: WorkItemUpdate, request: Request
) -> WorkItemRead:
    container: BrainContainer = get_container(request)
    work_item = await container.repositories.work_items.get(WorkItemId(work_item_id))
    if work_item is None:
        raise BrainAPIError("not_found", "work item not found", status_code=404)
    if payload.title is not None:
        work_item.title = payload.title
    if payload.description is not None:
        work_item.description = payload.description
    updated = await container.repositories.work_items.update(work_item)
    return _to_read(updated)


@router.post("/api/v1/work-items/{work_item_id}/analyze", status_code=202)
async def analyze_work_item(work_item_id: uuid.UUID, request: Request) -> AcceptedResult:
    from brain.domain.commands import AnalyzeWorkItemCommand

    container: BrainContainer = get_container(request)
    return await enqueue_command(
        container,
        CommandType.ANALYZE_WORK_ITEM,
        AnalyzeWorkItemCommand(work_item_id=WorkItemId(work_item_id)),
        correlation_id=request.state.correlation_id,
    )


@router.post("/api/v1/work-items/{work_item_id}/plan", status_code=202)
async def plan_work_item(work_item_id: uuid.UUID, request: Request) -> AcceptedResult:
    from brain.domain.commands import PlanWorkItemCommand

    container: BrainContainer = get_container(request)
    return await enqueue_command(
        container,
        CommandType.PLAN_WORK_ITEM,
        PlanWorkItemCommand(work_item_id=WorkItemId(work_item_id)),
        correlation_id=request.state.correlation_id,
    )


@router.post("/api/v1/work-items/{work_item_id}/context", status_code=202)
async def build_work_item_context(work_item_id: uuid.UUID, request: Request) -> AcceptedResult:
    from brain.domain.commands import BuildContextCommand

    container: BrainContainer = get_container(request)
    return await enqueue_command(
        container,
        CommandType.BUILD_CONTEXT,
        BuildContextCommand(work_item_id=WorkItemId(work_item_id)),
        correlation_id=request.state.correlation_id,
    )


@router.post("/api/v1/work-items/{work_item_id}/run", status_code=202)
async def run_work_item(work_item_id: uuid.UUID, request: Request) -> AcceptedResult:
    container: BrainContainer = get_container(request)
    work_item = await container.repositories.work_items.get(WorkItemId(work_item_id))
    if work_item is None:
        raise BrainAPIError("not_found", "work item not found", status_code=404)
    from brain.domain.commands import RunWorkItemCommand

    return await enqueue_command(
        container,
        CommandType.RUN_WORK_ITEM,
        RunWorkItemCommand(work_item_id=work_item.id),
        correlation_id=request.state.correlation_id,
    )


@router.post("/api/v1/work-items/{work_item_id}/pause", status_code=202)
async def pause_work_item(work_item_id: uuid.UUID, request: Request) -> AcceptedResult:
    del work_item_id, request
    return AcceptedResult(command_id="pause")


@router.post("/api/v1/work-items/{work_item_id}/resume", status_code=202)
async def resume_work_item(work_item_id: uuid.UUID, request: Request) -> AcceptedResult:
    del work_item_id, request
    return AcceptedResult(command_id="resume")


@router.post("/api/v1/work-items/{work_item_id}/cancel", status_code=202)
async def cancel_work_item(work_item_id: uuid.UUID, request: Request) -> AcceptedResult:
    del work_item_id, request
    return AcceptedResult(command_id="cancel")


@router.post("/api/v1/work-items/{work_item_id}/retry", status_code=202)
async def retry_work_item(work_item_id: uuid.UUID, request: Request) -> AcceptedResult:
    del work_item_id, request
    return AcceptedResult(command_id="retry")


@router.get("/api/v1/work-items/{work_item_id}/executions")
async def work_item_executions(work_item_id: uuid.UUID, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    executions = await container.repositories.executions.list_by_work_item(WorkItemId(work_item_id))
    return {
        "work_item_id": str(work_item_id),
        "executions": [e.model_dump(mode="json") for e in executions],
    }


@router.get("/api/v1/work-items/{work_item_id}/observations")
async def work_item_observations(work_item_id: uuid.UUID, request: Request) -> dict[str, object]:
    del request
    # Phase 26 introduces the engineering journal; empty for now.
    return {"work_item_id": str(work_item_id), "observations": []}
