"""Artifact domain: engineering outputs and inputs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import (
    ArtifactId,
    ExecutionId,
    ProjectId,
    RepositoryId,
    new_artifact_id,
)


class ArtifactType(StrEnum):
    SOURCE_FILE = "source_file"
    PATCH = "patch"
    COMMIT = "commit"
    BUILD = "build"
    TEST_REPORT = "test_report"
    CONTAINER_IMAGE = "container_image"
    CONFIGURATION = "configuration"
    DOCUMENT = "document"
    TRACE = "trace"
    COVERAGE_REPORT = "coverage_report"
    DIFF = "diff"


class Artifact(BaseModel):
    id: ArtifactId = Field(default_factory=new_artifact_id)
    project_id: ProjectId
    artifact_type: ArtifactType
    uri: str | None = None
    checksum: str | None = None
    repository_id: RepositoryId | None = None
    commit_sha: str | None = None
    execution_id: ExecutionId | None = None
