"""Documentation domain.

Documents are stored structurally (DocumentVersion + DocumentNode tree), never
reduced directly to arbitrary vector chunks.  Nodes preserve heading paths,
references to code/requirements/work items, and links.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import (
    DocumentId,
    DocumentVersionId,
    ProjectId,
    RepositoryId,
    RequirementId,
    WorkItemId,
    new_document_id,
    new_document_version_id,
)


class DocumentType(StrEnum):
    README = "readme"
    REQUIREMENTS = "requirements"
    ARCHITECTURE = "architecture"
    ADR = "adr"
    API_SPEC = "api_spec"
    GENERAL = "general"


class DocumentSource(BaseModel):
    provider: str
    uri: str
    mime_type: str | None = None
    external_ref: ExternalReference | None = None


class SourceArtifact(BaseModel):
    """Canonical input for the ingestion pipeline."""

    source_uri: str
    provider: str
    mime_type: str | None = None
    file_name: str | None = None
    revision: str | None = None
    content_hash: str | None = None
    raw_bytes_ref: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class DocumentVersion(BaseModel):
    id: DocumentVersionId = Field(default_factory=new_document_version_id)
    document_id: DocumentId
    source_version: str | None = None
    repository_id: RepositoryId | None = None
    commit_sha: str | None = None
    checksum: str
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_uri: str | None = None


class Document(BaseModel):
    id: DocumentId = Field(default_factory=new_document_id)
    project_id: ProjectId
    type: DocumentType = DocumentType.GENERAL
    title: str
    source: DocumentSource
    current_version_id: DocumentVersionId | None = None
    external_refs: list[ExternalReference] = Field(default_factory=list)


class DocumentNodeType(StrEnum):
    SECTION = "section"
    PARAGRAPH = "paragraph"
    CODE_BLOCK = "code_block"
    TABLE = "table"
    LIST = "list"
    FRONT_MATTER = "front_matter"
    ADR_CONTEXT = "adr_context"
    ADR_DECISION = "adr_decision"
    ADR_ALTERNATIVES = "adr_alternatives"
    ADR_CONSEQUENCES = "adr_consequences"


class DocumentNode(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    version_id: DocumentVersionId
    node_type: DocumentNodeType = DocumentNodeType.SECTION
    title: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    content: str = ""
    parent_id: uuid.UUID | None = None
    child_ids: list[uuid.UUID] = Field(default_factory=list)
    code_refs: list[str] = Field(default_factory=list)
    requirement_refs: list[RequirementId] = Field(default_factory=list)
    work_item_refs: list[WorkItemId] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
