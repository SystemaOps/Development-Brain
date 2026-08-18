"""Knowledge routes (Phase 23)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.schemas import KnowledgeSearchRequest
from brain.bootstrap.container import BrainContainer
from brain.domain.identity import ProjectId

router = APIRouter()


@router.post("/api/v1/knowledge/search")
async def knowledge_search(payload: KnowledgeSearchRequest, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    if payload.project_id is None:
        return {"hits": []}
    entities = await container.graph.find_entities(project_id=ProjectId(payload.project_id))
    lowered = payload.query.lower()
    matches = [e for e in entities if lowered in str(e.properties.get("name", "")).lower()][
        : payload.limit
    ]
    return {"hits": [e.model_dump(mode="json") for e in matches]}


@router.get("/api/v1/knowledge/entities/{entity_id}")
async def knowledge_entity(entity_id: uuid.UUID, request: Request) -> dict[str, object]:
    del entity_id, request
    return {}


@router.get("/api/v1/knowledge/entities/{entity_id}/relations")
async def knowledge_relations(entity_id: uuid.UUID, request: Request) -> dict[str, object]:
    del entity_id, request
    return {"relations": []}


@router.post("/api/v1/knowledge/traverse")
async def knowledge_traverse(request: Request) -> dict[str, object]:
    del request
    return {"nodes": []}


@router.get("/api/v1/knowledge/conflicts")
async def knowledge_conflicts(request: Request) -> dict[str, object]:
    del request
    return {"conflicts": []}


@router.post("/api/v1/knowledge/conflicts/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: uuid.UUID, request: Request) -> dict[str, object]:
    del conflict_id, request
    return {"status": "resolved"}
