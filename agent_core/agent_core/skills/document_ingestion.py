from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.models import Document, DocumentChunk, Project
from agent_core.skills.base import BaseSkill, SkillContext, SkillResult


class DocumentIngestionInput(BaseModel):
    """
    This skill assumes files were already uploaded through:

        POST /v1/documents/upload?project_key=...

    The skill loads the uploaded document chunks and passes them into the
    planning graph. UploadFile itself should stay in the FastAPI document route.
    """

    document_ids: list[str] = Field(default_factory=list)
    include_all_project_documents: bool = True
    max_chunks: int = 80


class DocumentIngestionOutput(BaseModel):
    project_key: str
    document_ids: list[str]
    chunk_ids: list[str]
    chunks: list[dict[str, Any]]


class DocumentInestionSkillTypoGuard:
    """
    Placeholder class only to make accidental imports fail loudly.
    Use DocumentIngestionSkill.
    """


class DocumentIngestionSkill(BaseSkill):
    name = "document_ingestion"
    description = (
        "Loads already-uploaded project documents and chunks so the planning "
        "workflow can summarize and extract requirements from them."
    )
    input_schema = DocumentIngestionInput
    output_schema = DocumentIngestionOutput
    side_effects = False

    def __init__(self, db: AsyncSession):
        self.db = db

    def can_handle(self, intent: str, context: SkillContext) -> float:
        lowered = intent.lower()

        if context.document_ids or context.chunk_ids:
            return 0.95

        keywords = [
            "readme",
            "document",
            "uploaded file",
            "markdown",
            "specification",
            "requirements document",
        ]

        if any(keyword in lowered for keyword in keywords):
            return 0.9

        return 0.25

    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict[str, Any],
    ) -> SkillResult:
        parsed = DocumentIngestionInput.model_validate(input_data or {})

        project = await self.db.scalar(
            select(Project).where(Project.project_key == context.project_key)
        )
        if not project:
            return SkillResult(
                skill_name=self.name,
                success=False,
                errors=[f"Project not found: {context.project_key}"],
            )

        documents = await self._load_documents(project.id, parsed)
        if not documents:
            output = DocumentIngestionOutput(
                project_key=context.project_key,
                document_ids=[],
                chunk_ids=[],
                chunks=[],
            )
            return SkillResult(
                skill_name=self.name,
                success=True,
                output=output.model_dump(mode="json"),
                errors=["No uploaded documents were found for this project."],
            )

        chunks = await self._load_chunks(
            project_id=project.id,
            document_ids=[document.id for document in documents],
            max_chunks=parsed.max_chunks,
        )

        output = DocumentIngestionOutput(
            project_key=context.project_key,
            document_ids=[str(document.id) for document in documents],
            chunk_ids=[str(chunk.id) for chunk in chunks],
            chunks=[
                {
                    "chunk_id": str(chunk.id),
                    "document_id": str(chunk.document_id),
                    "chunk_index": chunk.chunk_index,
                    "heading_path": chunk.heading_path,
                    "title": chunk.title,
                    "content": chunk.content,
                    "token_estimate": chunk.token_estimate,
                }
                for chunk in chunks
            ],
        )

        return SkillResult(
            skill_name=self.name,
            success=True,
            output=output.model_dump(mode="json"),
            source_refs=[
                {
                    "type": "document_chunk",
                    "id": str(chunk.id),
                    "title": chunk.title,
                }
                for chunk in chunks
            ],
        )

    async def _load_documents(
        self,
        project_id: UUID,
        parsed: DocumentIngestionInput,
    ) -> list[Document]:
        if parsed.document_ids:
            document_uuid_list = [UUID(item) for item in parsed.document_ids]
            result = await self.db.scalars(
                select(Document)
                .where(Document.project_id == project_id)
                .where(Document.id.in_(document_uuid_list))
                .order_by(Document.created_at.desc())
            )
            return list(result)

        if parsed.include_all_project_documents:
            result = await self.db.scalars(
                select(Document)
                .where(Document.project_id == project_id)
                .order_by(Document.created_at.desc())
            )
            return list(result)

        return []

    async def _load_chunks(
        self,
        *,
        project_id: UUID,
        document_ids: list[UUID],
        max_chunks: int,
    ) -> list[DocumentChunk]:
        result = await self.db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.project_id == project_id)
            .where(DocumentChunk.document_id.in_(document_ids))
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .limit(max_chunks)
        )
        return list(result)
