"""Project aggregate.

A Project is independent of any OpenProject project, Jira project, or GitLab
group.  It can exist without any external project-management provider.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ProjectId, RepositoryId, new_project_id


class ProjectStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class Project(BaseModel):
    id: ProjectId = Field(default_factory=new_project_id)
    name: str
    description: str | None = None
    status: ProjectStatus = ProjectStatus.PLANNED
    repositories: list[RepositoryId] = Field(default_factory=list)
    external_refs: list[ExternalReference] = Field(default_factory=list)
