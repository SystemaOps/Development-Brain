"""Context routes (Phase 23)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.errors import BrainAPIError
from brain.api.schemas import ContextBuildRequest, ContextBuildResult
from brain.bootstrap.container import BrainContainer
from brain.domain.context import ContextRequest, ContextType
from brain.domain.identity import ContextCapsuleId, ProjectId, RepositoryId, WorkItemId
from brain.ports.context import ContextCapsuleRepository

router = APIRouter()


@router.post("/api/v1/contexts/build", response_model=ContextBuildResult)
async def build_context(payload: ContextBuildRequest, request: Request) -> ContextBuildResult:
    container: BrainContainer = get_container(request)
    request_obj = ContextRequest(
        work_item_id=WorkItemId(payload.work_item_id),
        project_id=ProjectId(payload.project_id) if payload.project_id else None,
        repository_id=RepositoryId(payload.repository_id) if payload.repository_id else None,
        revision=payload.revision,
        context_type=ContextType(payload.context_type),
        preferred_token_budget=payload.preferred_token_budget,
        max_total_tokens=payload.max_total_tokens,
    )
    result = await container.context_engine.build(request_obj)
    return ContextBuildResult(
        capsule_id=result.capsule.id,
        work_item_id=result.capsule.work_item_id,
        context_type=result.capsule.context_type.value,
        total_tokens=result.capsule.total_tokens,
        model_budget_tokens=result.capsule.model_budget_tokens,
        candidates_included=result.candidates_included,
        candidates_gathered=result.candidates_gathered,
    )


@router.get("/api/v1/contexts/{capsule_id}")
async def get_context(capsule_id: uuid.UUID, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    capsules: ContextCapsuleRepository = container.repositories.context_capsules
    capsule = await capsules.get_capsule(ContextCapsuleId(capsule_id))
    if capsule is None:
        raise BrainAPIError("not_found", "context capsule not found", status_code=404)
    return capsule.model_dump(mode="json")


@router.get("/api/v1/contexts/{capsule_id}/explanation")
async def explain_context(capsule_id: uuid.UUID, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    capsules: ContextCapsuleRepository = container.repositories.context_capsules
    capsule = await capsules.get_capsule(ContextCapsuleId(capsule_id))
    if capsule is None:
        raise BrainAPIError("not_found", "context capsule not found", status_code=404)
    return {
        "capsule_id": str(capsule.id),
        "selected": [
            {
                "entity_type": c.entity_type,
                "entity_id": str(c.entity_id),
                "reason": c.reason,
                "retrieval_source": c.retrieval_source.value,
                "relevance_score": c.relevance_score,
            }
            for c in capsule.candidates
        ],
    }


@router.post("/api/v1/contexts/{capsule_id}/expand", status_code=202)
async def expand_context(capsule_id: uuid.UUID, request: Request) -> dict[str, str]:
    del capsule_id, request
    return {"status": "ACCEPTED"}


@router.post("/api/v1/contexts/search")
async def context_search(request: Request) -> dict[str, object]:
    del request
    return {"hits": []}


@router.post("/api/v1/contexts/symbol")
async def symbol_context(request: Request) -> dict[str, object]:
    del request
    return {"symbol": None}


@router.post("/api/v1/contexts/related-files")
async def related_files(request: Request) -> dict[str, object]:
    del request
    return {"files": []}


@router.post("/api/v1/contexts/related-tests")
async def related_tests(request: Request) -> dict[str, object]:
    del request
    return {"tests": []}
