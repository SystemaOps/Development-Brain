"""Document routes (Phase 23)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.errors import BrainAPIError
from brain.api.schemas import DocumentCreate, DocumentRead
from brain.bootstrap.container import BrainContainer
from brain.domain.documents import Document, DocumentSource
from brain.domain.identity import DocumentId, DocumentVersionId, ProjectId

router = APIRouter()


def _to_read(document: Document) -> DocumentRead:
    return DocumentRead(
        id=document.id,
        project_id=document.project_id,
        title=document.title,
        source_uri=document.source.uri,
        mime_type=document.source.mime_type or "",
        current_version_id=document.current_version_id,
    )


@router.post(
    "/api/v1/projects/{project_id}/documents", response_model=DocumentRead, status_code=201
)
async def register_document(
    project_id: uuid.UUID, payload: DocumentCreate, request: Request
) -> DocumentRead:
    container: BrainContainer = get_container(request)
    document = Document(
        project_id=ProjectId(project_id),
        title=payload.title or "",
        source=DocumentSource(provider="api", uri=payload.source_uri, mime_type=payload.mime_type),
    )
    created = await container.repositories.documents.create(document)
    return _to_read(created)


@router.get("/api/v1/documents/{document_id}", response_model=DocumentRead)
async def get_document(document_id: uuid.UUID, request: Request) -> DocumentRead:
    container: BrainContainer = get_container(request)
    document = await container.repositories.documents.get(DocumentId(document_id))
    if document is None:
        raise BrainAPIError("not_found", "document not found", status_code=404)
    return _to_read(document)


@router.get("/api/v1/documents/{document_id}/versions")
async def document_versions(document_id: uuid.UUID, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    versions = await container.repositories.documents.list_versions(DocumentId(document_id))
    return {
        "document_id": str(document_id),
        "versions": [v.model_dump(mode="json") for v in versions],
    }


@router.post("/api/v1/documents/{document_id}/ingest", status_code=202)
async def ingest_document(document_id: uuid.UUID, request: Request) -> dict[str, str]:
    del document_id, request
    return {"status": "ACCEPTED"}


@router.post("/api/v1/documents/{document_id}/reprocess", status_code=202)
async def reprocess_document(document_id: uuid.UUID, request: Request) -> dict[str, str]:
    del document_id, request
    return {"status": "ACCEPTED"}


@router.get("/api/v1/documents/{document_id}/structure")
async def document_structure(document_id: uuid.UUID, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    document = await container.repositories.documents.get(DocumentId(document_id))
    if document is None:
        raise BrainAPIError("not_found", "document not found", status_code=404)
    nodes: list[dict[str, object]] = []
    if document.current_version_id is not None:
        raw_nodes = await container.repositories.documents.list_nodes(
            DocumentVersionId(document.current_version_id)
        )
        nodes = [node.model_dump(mode="json") for node in raw_nodes]
    return {
        "document_id": str(document_id),
        "nodes": nodes,
    }


@router.get("/api/v1/documents/{document_id}/knowledge")
async def document_knowledge(document_id: uuid.UUID, request: Request) -> dict[str, object]:
    del document_id, request
    return {"knowledge": []}
