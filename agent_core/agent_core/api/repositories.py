from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.deps import get_db
from agent_core.domain.repositories import (
    DEFAULT_REPOSITORY_DENYLIST,
    RepositoryBinding,
    RepositoryPathError,
)
from agent_core.schemas import (
    CodeRelationshipView,
    CodeSymbolView,
    RepositoryBindingCreate,
    RepositoryBindingView,
    RepositoryIndexView,
    RepositorySnapshotView,
)
from agent_core.services.repository_analysis_service import (
    RepositoryAnalysisService,
)

router = APIRouter(prefix="/v1/projects/{project_key}/repositories", tags=["repositories"])


@router.post("", response_model=RepositoryBindingView)
async def bind_repository(
    project_key: str,
    payload: RepositoryBindingCreate,
    db: AsyncSession = Depends(get_db),
):
    denylist = payload.denylist
    if denylist is None:
        denylist = list(DEFAULT_REPOSITORY_DENYLIST)
    binding = RepositoryBinding(
        repository_key=payload.repository_key,
        mount_path=payload.mount_path,
        access_mode=payload.access_mode,
        write_allowlist=tuple(payload.write_allowlist),
        denylist=tuple(denylist),
        command_allowlist=tuple(payload.command_allowlist),
    )
    try:
        stored = await RepositoryAnalysisService(db).bind_repository(
            project_key=project_key,
            binding=binding,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    except RepositoryPathError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _binding_view(stored)


@router.get("/{repository_key}", response_model=RepositoryBindingView)
async def get_repository_binding(
    project_key: str,
    repository_key: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        binding = await RepositoryAnalysisService(db).get_binding(
            project_key=project_key,
            repository_key=repository_key,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Repository binding not found")
    return _binding_view(binding)


@router.post("/{repository_key}/index", response_model=RepositoryIndexView)
async def index_repository(
    project_key: str,
    repository_key: str,
    project_to_graph: bool = Query(default=False),
    upsert_to_vector: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RepositoryAnalysisService(db).index_repository(
            project_key=project_key,
            repository_key=repository_key,
            project_to_graph=project_to_graph,
            upsert_to_vector=upsert_to_vector,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Repository binding not found")
    except RepositoryPathError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{repository_key}/snapshot", response_model=RepositorySnapshotView)
async def get_repository_snapshot(
    project_key: str,
    repository_key: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RepositoryAnalysisService(db).snapshot(
            project_key=project_key,
            repository_key=repository_key,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Repository binding not found")
    except RepositoryPathError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{repository_key}/symbols", response_model=list[CodeSymbolView])
async def list_repository_symbols(
    project_key: str,
    repository_key: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RepositoryAnalysisService(db).list_symbols(
            project_key=project_key,
            repository_key=repository_key,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/{repository_key}/relationships", response_model=list[CodeRelationshipView])
async def list_repository_relationships(
    project_key: str,
    repository_key: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RepositoryAnalysisService(db).list_relationships(
            project_key=project_key,
            repository_key=repository_key,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/{repository_key}/search", response_model=list[dict])
async def search_repository_context(
    project_key: str,
    repository_key: str,
    query: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    try:
        await RepositoryAnalysisService(db).get_binding(
            project_key=project_key,
            repository_key=repository_key,
        )
        return await RepositoryAnalysisService(db).search_repository_context(
            query=query,
            limit=limit,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Repository binding not found")


def _binding_view(binding: RepositoryBinding) -> RepositoryBindingView:
    return RepositoryBindingView(
        repository_key=binding.repository_key,
        mount_path=binding.mount_path,
        access_mode=binding.access_mode,
        write_allowlist=list(binding.write_allowlist),
        denylist=list(binding.denylist),
        command_allowlist=list(binding.command_allowlist),
    )
