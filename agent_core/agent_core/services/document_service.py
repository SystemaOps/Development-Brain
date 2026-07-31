from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.ingestion.markdown_splitter import split_markdown_by_headings
from agent_core.models import Document, DocumentChunk, Project


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upload_and_chunk(self, *, project_key: str, file: UploadFile) -> tuple[Document, int]:
        project = await self.db.scalar(select(Project).where(Project.project_key == project_key))
        if not project:
            raise KeyError(project_key)
        raw = await file.read()
        text = raw.decode("utf-8", errors="replace")
        suffix = Path(file.filename or "").suffix.lower()
        doc_type = "readme" if (file.filename or "").lower() == "readme.md" else ("markdown" if suffix in {".md", ".markdown"} else "text")
        document = Document(
            project_id=project.id,
            filename=file.filename or "uploaded-document",
            document_type=doc_type,
            mime_type=file.content_type,
            content_hash=sha256_text(text),
            raw_text=text,
            status="chunked",
        )
        self.db.add(document)
        await self.db.flush()
        chunks = split_markdown_by_headings(text)
        for i, chunk in enumerate(chunks):
            self.db.add(DocumentChunk(
                project_id=project.id,
                document_id=document.id,
                chunk_index=i,
                heading_path=chunk.heading_path,
                title=chunk.title,
                content=chunk.content,
                token_estimate=chunk.token_estimate,
                content_hash=sha256_text(chunk.content),
            ))
        await self.db.commit()
        await self.db.refresh(document)
        return document, len(chunks)

    async def list_chunks(self, document_id: UUID) -> list[DocumentChunk]:
        result = await self.db.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index)
        )
        return list(result)
