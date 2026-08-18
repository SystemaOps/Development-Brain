"""Execution routes (Phase 23)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.errors import BrainAPIError
from brain.api.schemas import ExecutionCreate, ExecutionRead
from brain.bootstrap.container import BrainContainer
from brain.domain.executions import Execution
from brain.domain.identity import (
    ActorId,
    ExecutionId,
    WorkItemId,
    new_workflow_id,
)

router = APIRouter()


def _to_read(execution: Execution) -> ExecutionRead:
    return ExecutionRead(
        id=execution.id,
        workflow_id=execution.workflow_id,
        work_item_id=execution.work_item_id,
        executor_id=execution.executor_id,
        status=execution.status.value,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
    )


@router.post("/api/v1/executions", response_model=ExecutionRead, status_code=201)
async def start_execution(payload: ExecutionCreate, request: Request) -> ExecutionRead:
    container: BrainContainer = get_container(request)
    work_item = await container.repositories.work_items.get(WorkItemId(payload.work_item_id))
    if work_item is None:
        raise BrainAPIError("not_found", "work item not found", status_code=404)
    descriptors = container.executor_descriptors
    if not descriptors:
        raise BrainAPIError("no_executor", "no executor available", status_code=409)
    executor_id: ActorId
    if payload.executor_id:
        executor_id = ActorId(payload.executor_id)
    else:
        executor_id = ActorId(descriptors[0].executor_id)
    execution = Execution(
        workflow_id=new_workflow_id(),
        work_item_id=work_item.id,
        executor_id=executor_id,
    )
    created = await container.repositories.executions.create(execution)
    return _to_read(created)


@router.get("/api/v1/executions/{execution_id}", response_model=ExecutionRead)
async def get_execution(execution_id: uuid.UUID, request: Request) -> ExecutionRead:
    container: BrainContainer = get_container(request)
    execution = await container.repositories.executions.get(ExecutionId(execution_id))
    if execution is None:
        raise BrainAPIError("not_found", "execution not found", status_code=404)
    return _to_read(execution)


@router.post("/api/v1/executions/{execution_id}/cancel", status_code=202)
async def cancel_execution(execution_id: uuid.UUID, request: Request) -> dict[str, str]:
    del execution_id, request
    return {"status": "ACCEPTED"}


@router.post("/api/v1/executions/{execution_id}/retry", status_code=202)
async def retry_execution(execution_id: uuid.UUID, request: Request) -> dict[str, str]:
    del execution_id, request
    return {"status": "ACCEPTED"}


@router.get("/api/v1/executions/{execution_id}/artifacts")
async def execution_artifacts(execution_id: uuid.UUID, request: Request) -> dict[str, object]:
    del request
    return {"execution_id": str(execution_id), "artifacts": []}


@router.get("/api/v1/executions/{execution_id}/evidence")
async def execution_evidence(execution_id: uuid.UUID, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    evidence = await container.repositories.evidence.list_by_execution(ExecutionId(execution_id))
    return {
        "execution_id": str(execution_id),
        "evidence": [e.model_dump(mode="json") for e in evidence],
    }


@router.get("/api/v1/executions/{execution_id}/diff")
async def execution_diff(execution_id: uuid.UUID, request: Request) -> dict[str, object]:
    del execution_id, request
    return {"diff": None}
