"""Repository routes (Phase 23)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.errors import BrainAPIError
from brain.api.schemas import (
    ImpactAnalysisRequest,
    RepositoryCreate,
    RepositoryRead,
)
from brain.bootstrap.container import BrainContainer
from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.repositories import Repository

router = APIRouter()


def _to_read(repository: Repository) -> RepositoryRead:
    return RepositoryRead(
        id=repository.id,
        project_id=repository.project_id,
        name=repository.name,
        clone_url=repository.clone_url,
        default_branch=repository.default_branch,
        current_revision=repository.current_revision,
        external_refs=[ref.model_dump(mode="json") for ref in repository.external_refs],
    )


@router.post(
    "/api/v1/projects/{project_id}/repositories", response_model=RepositoryRead, status_code=201
)
async def register_repository(
    project_id: uuid.UUID, payload: RepositoryCreate, request: Request
) -> RepositoryRead:
    container: BrainContainer = get_container(request)
    project = await container.repositories.projects.get(ProjectId(project_id))
    if project is None:
        raise BrainAPIError("not_found", "project not found", status_code=404)
    repository = Repository(
        project_id=ProjectId(project_id),
        name=payload.name,
        clone_url=payload.clone_url,
        default_branch=payload.default_branch,
    )
    created = await container.repositories.repositories.create(repository)
    if repository.id not in project.repositories:
        project.repositories.append(repository.id)
        await container.repositories.projects.update(project)
    return _to_read(created)


@router.get("/api/v1/repositories/{repository_id}", response_model=RepositoryRead)
async def get_repository(repository_id: uuid.UUID, request: Request) -> RepositoryRead:
    container: BrainContainer = get_container(request)
    repository = await container.repositories.repositories.get(RepositoryId(repository_id))
    if repository is None:
        raise BrainAPIError("not_found", "repository not found", status_code=404)
    return _to_read(repository)


@router.post("/api/v1/repositories/{repository_id}/sync", status_code=202)
async def sync_repository(repository_id: uuid.UUID, request: Request) -> dict[str, str]:
    del repository_id, request
    # Phase 24+ enqueues a SyncRepositoryCommand; accepted for now.
    return {"status": "ACCEPTED"}


@router.post("/api/v1/repositories/{repository_id}/ingest", status_code=202)
async def ingest_repository(repository_id: uuid.UUID, request: Request) -> dict[str, str]:
    del repository_id, request
    # Phase 24+ enqueues an IngestRepositoryCommand; accepted for now.
    return {"status": "ACCEPTED"}


@router.get("/api/v1/repositories/{repository_id}/status")
async def repository_status(repository_id: uuid.UUID, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    repository = await container.repositories.repositories.get(RepositoryId(repository_id))
    if repository is None:
        raise BrainAPIError("not_found", "repository not found", status_code=404)
    return {
        "repository_id": str(repository_id),
        "current_revision": repository.current_revision,
        "default_branch": repository.default_branch,
    }


@router.get("/api/v1/repositories/{repository_id}/changes")
async def repository_changes(repository_id: uuid.UUID, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    change_sets = container.repositories.repository_change_sets
    result = await change_sets.list_change_sets(RepositoryId(repository_id))
    return {
        "repository_id": str(repository_id),
        "changes": [c.model_dump(mode="json") for c in result],
    }


@router.get("/api/v1/repositories/{repository_id}/symbols")
async def repository_symbols(
    repository_id: uuid.UUID,
    request: Request,
    revision: str | None = None,
    query: str | None = None,
) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    code_graph = container.repositories.code_graph
    repository = await container.repositories.repositories.get(RepositoryId(repository_id))
    if repository is None:
        raise BrainAPIError("not_found", "repository not found", status_code=404)
    revision = revision or repository.current_revision
    symbols = await code_graph.list_symbols(RepositoryId(repository_id), revision or "")
    if query:
        lowered = query.lower()
        symbols = [
            s for s in symbols if lowered in s.qualified_name.lower() or lowered in s.name.lower()
        ]
    return {
        "repository_id": str(repository_id),
        "symbols": [s.model_dump(mode="json") for s in symbols],
    }


@router.post("/api/v1/repositories/{repository_id}/impact-analysis")
async def repository_impact_analysis(
    repository_id: uuid.UUID, payload: ImpactAnalysisRequest, request: Request
) -> dict[str, object]:
    del repository_id
    container: BrainContainer = get_container(request)
    from brain.application.impact_analysis import ImpactAnalysisService

    service = ImpactAnalysisService(repository=container.repositories.code_graph)
    analysis = await service.analyze(
        RepositoryId(payload.repository_id),
        payload.revision,
        target_symbols=payload.target_symbols,
        task_concepts=payload.task_concepts,
    )
    return {
        "repository_id": str(analysis.repository_id),
        "revision": analysis.revision,
        "primary_symbols": [s.model_dump(mode="json") for s in analysis.primary_symbols],
        "related_files": analysis.related_files,
        "related_tests": analysis.related_tests,
        "interfaces": analysis.interfaces,
        "configuration": analysis.configuration,
        "risk_score": analysis.risk_score,
    }
