"""Requirement routes (Phase 23)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.errors import BrainAPIError
from brain.api.schemas import RequirementCreate, RequirementRead, RequirementUpdate
from brain.bootstrap.container import BrainContainer
from brain.domain.identity import ProjectId, RequirementId
from brain.domain.requirements import Requirement

router = APIRouter()


def _to_read(requirement: Requirement) -> RequirementRead:
    return RequirementRead(
        id=requirement.id,
        project_id=requirement.project_id,
        key=requirement.key,
        title=requirement.title,
        description=requirement.description,
        status=requirement.status.value,
    )


@router.post("/api/v1/requirements", response_model=RequirementRead, status_code=201)
async def create_requirement(payload: RequirementCreate, request: Request) -> RequirementRead:
    container: BrainContainer = get_container(request)
    requirement = Requirement(
        project_id=ProjectId(payload.project_id),
        title=payload.title,
        description=payload.description,
        key=payload.key,
    )
    created = await container.repositories.requirements.create(requirement)
    return _to_read(created)


@router.get("/api/v1/requirements/{requirement_id}", response_model=RequirementRead)
async def get_requirement(requirement_id: uuid.UUID, request: Request) -> RequirementRead:
    container: BrainContainer = get_container(request)
    requirement = await container.repositories.requirements.get(RequirementId(requirement_id))
    if requirement is None:
        raise BrainAPIError("not_found", "requirement not found", status_code=404)
    return _to_read(requirement)


@router.patch("/api/v1/requirements/{requirement_id}", response_model=RequirementRead)
async def update_requirement(
    requirement_id: uuid.UUID, payload: RequirementUpdate, request: Request
) -> RequirementRead:
    container: BrainContainer = get_container(request)
    requirement = await container.repositories.requirements.get(RequirementId(requirement_id))
    if requirement is None:
        raise BrainAPIError("not_found", "requirement not found", status_code=404)
    if payload.title is not None:
        requirement.title = payload.title
    if payload.description is not None:
        requirement.description = payload.description
    updated = await container.repositories.requirements.update(requirement)
    return _to_read(updated)


@router.post("/api/v1/requirements/extract", status_code=202)
async def extract_requirements(request: Request) -> dict[str, str]:
    from brain.api.commands import enqueue_command
    from brain.domain.commands import CommandType, ExtractRequirementsCommand
    from brain.domain.identity import ProjectId

    container: BrainContainer = get_container(request)
    projects = await container.repositories.projects.list()
    if not projects:
        return {"status": "ACCEPTED", "command_id": "none"}
    result = await enqueue_command(
        container,
        CommandType.EXTRACT_REQUIREMENTS,
        ExtractRequirementsCommand(project_id=ProjectId(projects[0].id)),
        correlation_id=request.state.correlation_id,
    )
    return result.model_dump(mode="json")


@router.post("/api/v1/requirements/{requirement_id}/analyze", status_code=202)
async def analyze_requirement(requirement_id: uuid.UUID, request: Request) -> dict[str, str]:
    del requirement_id, request
    return {"status": "ACCEPTED"}


@router.get("/api/v1/requirements/{requirement_id}/coverage")
async def requirement_coverage(requirement_id: uuid.UUID, request: Request) -> dict[str, object]:
    del requirement_id, request
    return {"coverage": []}


@router.get("/api/v1/requirements/{requirement_id}/related-code")
async def requirement_related_code(
    requirement_id: uuid.UUID, request: Request
) -> dict[str, object]:
    del requirement_id, request
    return {"files": []}
