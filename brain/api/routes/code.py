"""Code intelligence routes (Phase 23)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.schemas import CodeSearchRequest, ImpactAnalysisRequest
from brain.bootstrap.container import BrainContainer
from brain.domain.identity import RepositoryId

router = APIRouter()


@router.get("/api/v1/code/symbols/{symbol_name}")
async def symbol_detail(symbol_name: str, request: Request) -> dict[str, object]:
    del symbol_name, request
    return {}


@router.get("/api/v1/code/symbols/{symbol_name}/callers")
async def symbol_callers(symbol_name: str, request: Request) -> dict[str, object]:
    del symbol_name, request
    return {"callers": []}


@router.get("/api/v1/code/symbols/{symbol_name}/callees")
async def symbol_callees(symbol_name: str, request: Request) -> dict[str, object]:
    del symbol_name, request
    return {"callees": []}


@router.get("/api/v1/code/symbols/{symbol_name}/tests")
async def symbol_tests(symbol_name: str, request: Request) -> dict[str, object]:
    del symbol_name, request
    return {"tests": []}


@router.post("/api/v1/code/search")
async def code_search(payload: CodeSearchRequest, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    code_graph = container.repositories.code_graph
    if payload.repository_id is None:
        return {"symbols": []}
    repository_id = RepositoryId(payload.repository_id)
    symbols = await code_graph.list_symbols(repository_id, payload.revision or "")
    lowered = payload.query.lower()
    matches = [
        s for s in symbols if lowered in s.qualified_name.lower() or lowered in s.name.lower()
    ][: payload.limit]
    return {"symbols": [s.model_dump(mode="json") for s in matches]}


@router.post("/api/v1/code/impact")
async def code_impact(payload: ImpactAnalysisRequest, request: Request) -> dict[str, object]:
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


@router.get("/api/v1/code/files/{file_id}/dependencies")
async def file_dependencies(file_id: str, request: Request) -> dict[str, object]:
    del file_id, request
    return {"dependencies": []}
