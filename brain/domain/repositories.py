"""Repository aggregate.

A Repository is a first-class input to the brain: a cloneable source of code,
documentation, and engineering history.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ProjectId, RepositoryId, new_repository_id


class Repository(BaseModel):
    id: RepositoryId = Field(default_factory=new_repository_id)
    project_id: ProjectId
    name: str
    clone_url: str
    default_branch: str = "main"
    current_revision: str | None = None
    external_refs: list[ExternalReference] = Field(default_factory=list)
