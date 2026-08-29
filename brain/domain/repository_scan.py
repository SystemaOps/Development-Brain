"""Repository scanning domain model.

Phase 4 makes Git repositories first-class inputs to the brain.  This module
carries the *scan artifacts*:

- :class:`RepositorySnapshot` — what the repository looks like at one revision
  (tree, detected languages, manifests, CI/deployment files, documentation and
  test roots);
- :class:`RepositoryChangeSet` — which files changed between two revisions,
  each classified into a :class:`FileCategory`.

The classification rules live here as pure domain logic so any adapter
(GitLab webhook payloads, local git, GitHub events) can be normalized against
the same categories.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import (
    RepositoryChangeSetId,
    RepositoryId,
    RepositorySnapshotId,
    new_repository_change_set_id,
    new_repository_snapshot_id,
)


class FileCategory(StrEnum):
    """Coarse classification of a repository file.

    Matches the categories Phase 4.5 must emit: specialized ingestion jobs
    (documentation -> document ingestion, source/test -> code intelligence,
    manifest/deployment/schema -> topology discovery, ...).
    """

    SOURCE = "source"
    TEST = "test"
    DOCUMENTATION = "documentation"
    MANIFEST = "manifest"
    CONFIGURATION = "configuration"
    DEPLOYMENT = "deployment"
    SCHEMA = "schema"
    UNKNOWN = "unknown"


_MANIFEST_NAMES = frozenset(
    {
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "setup.py",
        "setup.cfg",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "go.mod",
        "go.sum",
        "Cargo.toml",
        "Cargo.lock",
        "Gemfile",
        "Gemfile.lock",
        "pom.xml",
        "build.gradle",
        "gradle.properties",
        "composer.json",
        "Dockerfile",
    }
)

_DEPLOYMENT_NAMES = frozenset(
    {
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "docker-compose.override.yml",
    }
)

_CI_NAMES = frozenset(
    {
        ".gitlab-ci.yml",
        ".gitlab-ci.yaml",
        "Jenkinsfile",
        ".travis.yml",
        ".circleci/config.yml",
        "azure-pipelines.yml",
    }
)

_DOC_EXTENSIONS = frozenset({".md", ".markdown", ".rst", ".adoc", ".txt"})
_SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".scala",
        ".sh",
        ".bash",
        ".sql",
    }
)
_SCHEMA_EXTENSIONS = frozenset({".sql", ".proto", ".graphql"})
_CONFIG_EXTENSIONS = frozenset({".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"})
_TEST_NAMES = frozenset(
    {
        "conftest.py",
        "test_requirements.txt",
        "pytest.ini",
    }
)


def classify_file(path: str) -> FileCategory:
    """Classify a repository file path into a :class:`FileCategory`.

    Order matters: deployment names beat generic yaml config, tests beat
    source, manifests beat configuration.
    """
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    lower = name.lower()
    parts = [part.lower() for part in normalized.split("/")]

    if lower in _MANIFEST_NAMES or lower.endswith(".toml"):
        return FileCategory.MANIFEST
    if lower in _DEPLOYMENT_NAMES or lower in _CI_NAMES or lower == "dockerfile":
        return FileCategory.DEPLOYMENT
    if ".github" in parts or ".gitlab" in parts:
        return FileCategory.DEPLOYMENT
    if _is_test(normalized, parts):
        return FileCategory.TEST
    if _is_documentation(normalized, lower, parts):
        return FileCategory.DOCUMENTATION
    if normalized.endswith(tuple(_SCHEMA_EXTENSIONS)):
        return FileCategory.SCHEMA
    if normalized.endswith(tuple(_SOURCE_EXTENSIONS)):
        return FileCategory.SOURCE
    if normalized.endswith(tuple(_CONFIG_EXTENSIONS)):
        return FileCategory.CONFIGURATION
    return FileCategory.UNKNOWN


def _is_test(path: str, parts: list[str]) -> bool:
    if any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in parts):
        return True
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.go")


def _is_documentation(path: str, lower_name: str, parts: list[str]) -> bool:
    if any(part in {"docs", "doc", "documentation"} for part in parts):
        return True
    if path.endswith(tuple(_DOC_EXTENSIONS)):
        return True
    return lower_name in {"readme", "readme.md", "changelog", "changelog.md", "contributing"}


class RepositorySnapshot(BaseModel):
    """The repository tree summarized at one exact revision."""

    id: RepositorySnapshotId = Field(default_factory=new_repository_snapshot_id)
    repository_id: RepositoryId
    revision: str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tree: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    manifest_files: list[str] = Field(default_factory=list)
    dockerfiles: list[str] = Field(default_factory=list)
    compose_files: list[str] = Field(default_factory=list)
    ci_configuration: list[str] = Field(default_factory=list)
    documentation_roots: list[str] = Field(default_factory=list)
    test_roots: list[str] = Field(default_factory=list)


class ChangedFile(BaseModel):
    """One changed file with its classification."""

    path: str
    category: FileCategory
    change_type: str = "modified"


class RepositoryChangeSet(BaseModel):
    """Classified set of files changed between two revisions."""

    id: RepositoryChangeSetId = Field(default_factory=new_repository_change_set_id)
    repository_id: RepositoryId
    old_revision: str | None = None
    new_revision: str
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    files: list[ChangedFile] = Field(default_factory=list)


def classify_changed_files(paths: list[str]) -> list[ChangedFile]:
    """Classify every path in ``paths`` into a :class:`ChangedFile`."""
    return [ChangedFile(path=path, category=classify_file(path)) for path in paths]


__all__ = [
    "ChangedFile",
    "FileCategory",
    "RepositoryChangeSet",
    "RepositorySnapshot",
    "classify_changed_files",
    "classify_file",
]
