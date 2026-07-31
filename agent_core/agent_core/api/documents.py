from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.deps import get_db
from agent_core.models import Project
from agent_core.schemas import DocumentChunkView, DocumentView
from agent_core.services.document_service import DocumentService

router = APIRouter(prefix="/v1/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentView)
async def upload_document(project_key: str, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    try:
        document, chunk_count = await DocumentService(db).upload_and_chunk(project_key=project_key, file=file)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    project = await db.get(Project, document.project_id)
    return DocumentView(id=document.id, project_key=project.project_key, filename=document.filename, document_type=document.document_type, status=document.status, chunk_count=chunk_count)


@router.get("/{document_id}/chunks", response_model=list[DocumentChunkView])
async def list_chunks(document_id: UUID, db: AsyncSession = Depends(get_db)):
    chunks = await DocumentService(db).list_chunks(document_id)
    return [DocumentChunkView(id=c.id, chunk_index=c.chunk_index, heading_path=c.heading_path, title=c.title, token_estimate=c.token_estimate) for c in chunks]
