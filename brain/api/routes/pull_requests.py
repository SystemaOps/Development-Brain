"""Pull request routes (Phase 23). Provider-neutral."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.errors import BrainAPIError
from brain.api.schemas import PullRequestCreate, PullRequestRead
from brain.bootstrap.container import BrainContainer
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ExecutionId

router = APIRouter()


@router.post("/api/v1/executions/{execution_id}/pull-request", response_model=PullRequestRead)
async def create_pull_request(
    execution_id: uuid.UUID, payload: PullRequestCreate, request: Request
) -> PullRequestRead:
    del payload
    container: BrainContainer = get_container(request)
    pr_port = container.pull_requests
    if pr_port is None:
        raise BrainAPIError(
            "pr_unavailable", "no pull-request provider configured", status_code=409
        )
    execution = await container.repositories.executions.get(ExecutionId(execution_id))
    if execution is None:
        raise BrainAPIError("not_found", "execution not found", status_code=404)

    # The repository is derived from the first repository of the project the
    # work item belongs to; a real integration will resolve it precisely.
    work_item = await container.repositories.work_items.get(execution.work_item_id)
    if work_item is None:
        raise BrainAPIError("not_found", "work item not found", status_code=404)
    repos = await container.repositories.repositories.list_by_project(work_item.project_id)
    if not repos:
        raise BrainAPIError("no_repository", "no repository for work item", status_code=409)
    repository = repos[0]

    ref: ExternalReference = await pr_port.create_pull_request(
        repository=repository,
        source_branch=f"brain/{execution.id}",
        target_branch=repository.default_branch,
        title=work_item.title,
        description=work_item.description,
    )
    return PullRequestRead(
        id=ref.external_id,
        external_ref=ref.model_dump(mode="json"),
        status="created",
    )


@router.get("/api/v1/pull-requests/{pr_id}", response_model=PullRequestRead)
async def get_pull_request(pr_id: str, request: Request) -> PullRequestRead:
    container: BrainContainer = get_container(request)
    pr_port = container.pull_requests
    if pr_port is None:
        raise BrainAPIError(
            "pr_unavailable", "no pull-request provider configured", status_code=409
        )
    pull_request = await pr_port.get_pull_request(
        ExternalReference(provider="fake", external_id=pr_id, external_type="pull_request")
    )
    return PullRequestRead(
        id=str(pull_request.id),
        external_ref={
            "provider": "fake",
            "external_id": pr_id,
            "state": pull_request.state,
        },
        status=pull_request.state,
    )


@router.post("/api/v1/pull-requests/{pr_id}/refresh", response_model=PullRequestRead)
async def refresh_pull_request(pr_id: str, request: Request) -> PullRequestRead:
    container: BrainContainer = get_container(request)
    pr_port = container.pull_requests
    if pr_port is None:
        raise BrainAPIError(
            "pr_unavailable", "no pull-request provider configured", status_code=409
        )
    pull_request = await pr_port.get_pull_request(
        ExternalReference(provider="fake", external_id=pr_id, external_type="pull_request")
    )
    return PullRequestRead(id=str(pull_request.id), status=pull_request.state)
