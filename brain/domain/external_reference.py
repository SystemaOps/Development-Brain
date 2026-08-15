"""External references connect brain entities to external provider systems.

External IDs (Jira keys, OpenProject work-package numbers, Confluence page
IDs, ...) are NEVER used as internal primary keys.  They are stored only as
``ExternalReference`` records so the brain identity stays stable when a
provider is replaced.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from brain.domain.identity import DocumentId, WorkItemId


class ExternalReference(BaseModel):
    """A pointer to an entity in an external provider system."""

    provider: str
    external_id: str
    external_type: str | None = None
    url: str | None = None
    namespace: str | None = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.provider}:{self.external_id}"


class SourceReference(BaseModel):
    """Where a piece of knowledge or a requirement originated."""

    provider: str
    reference: str | None = None
    url: str | None = None
    document_id: DocumentId | None = None
    work_item_id: WorkItemId | None = None
    heading_path: list[str] = Field(default_factory=list)
