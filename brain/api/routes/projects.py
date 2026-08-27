"""Project routes (Phase 23)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.errors import BrainAPIError
from brain.api.schemas import ProjectCreate, ProjectRead, ProjectUpdate
from brain.bootstrap.container import BrainContainer
from brain.domain.identity import ProjectId
from brain.domain.projects import Project

router = APIRouter()


def _to_read(project: Project) -> ProjectRead:
    return ProjectRead(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status.value,
        repositories=list(project.repositories),
        external_refs=[ref.model_dump(mode="json") for ref in project.external_refs],
    )


@router.post("/api/v1/projects", response_model=ProjectRead, status_code=201)
async def create_project(payload: ProjectCreate, request: Request) -> ProjectRead:
    container: BrainContainer = get_container(request)
    project = Project(name=payload.name, description=payload.description)
    created = await container.repositories.projects.create(project)
    return _to_read(created)


@router.get("/api/v1/projects", response_model=list[ProjectRead])
async def list_projects(request: Request) -> list[ProjectRead]:
    container: BrainContainer = get_container(request)
    projects = await container.repositories.projects.list()
    return [_to_read(project) for project in projects]


@router.get("/api/v1/projects/{project_id}", response_model=ProjectRead)
async def get_project(project_id: uuid.UUID, request: Request) -> ProjectRead:
    container: BrainContainer = get_container(request)
    project = await container.repositories.projects.get(ProjectId(project_id))
    if project is None:
        raise BrainAPIError("not_found", "project not found", status_code=404)
    return _to_read(project)


@router.patch("/api/v1/projects/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID, payload: ProjectUpdate, request: Request
) -> ProjectRead:
    container: BrainContainer = get_container(request)
    project = await container.repositories.projects.get(ProjectId(project_id))
    if project is None:
        raise BrainAPIError("not_found", "project not found", status_code=404)
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    updated = await container.repositories.projects.update(project)
    return _to_read(updated)


@router.post("/api/v1/projects/{project_id}/analyze", status_code=202)
async def analyze_project(project_id: uuid.UUID, request: Request) -> dict[str, str]:
    from brain.api.commands import enqueue_command
    from brain.domain.commands import AnalyzeProjectCommand, CommandType

    container: BrainContainer = get_container(request)
    result = await enqueue_command(
        container,
        CommandType.ANALYZE_PROJECT,
        AnalyzeProjectCommand(project_id=ProjectId(project_id)),
        correlation_id=request.state.correlation_id,
    )
    return result.model_dump(mode="json")


@router.get("/api/v1/projects/{project_id}/topology")
async def project_topology(project_id: uuid.UUID, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    catalog = container.repositories.software_catalog
    systems = await catalog.list_systems(ProjectId(project_id))
    components = await catalog.list_components(ProjectId(project_id))
    interfaces = await catalog.list_interfaces(ProjectId(project_id))
    resources = await catalog.list_resources(ProjectId(project_id))
    return {
        "project_id": str(project_id),
        "systems": [s.model_dump(mode="json") for s in systems],
        "components": [c.model_dump(mode="json") for c in components],
        "interfaces": [i.model_dump(mode="json") for i in interfaces],
        "resources": [r.model_dump(mode="json") for r in resources],
    }


@router.get("/api/v1/projects/{project_id}/knowledge-status")
async def project_knowledge_status(project_id: uuid.UUID, request: Request) -> dict[str, object]:
    del project_id, request
    return {"status": "unknown"}
