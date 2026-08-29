"""Repository scanner.

Walks a checked-out repository tree and produces a
:class:`~brain.domain.repository_scan.RepositorySnapshot`: tree summary,
detected languages, manifest files, Dockerfiles, Compose files, CI
configuration, and documentation/test roots.  Used on repository registration
(Phase 4.3) and to refresh snapshots after revision changes.
"""

from __future__ import annotations

from pathlib import Path

from brain.domain.identity import RepositoryId
from brain.domain.repository_scan import (
    FileCategory,
    RepositorySnapshot,
    classify_file,
)

_DOCKERFILE_NAMES = frozenset({"dockerfile", "dockerfile.dev", "dockerfile.prod"})
_COMPOSE_NAMES = frozenset(
    {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
)
_CI_PATHS = frozenset(
    {
        ".gitlab-ci.yml",
        ".gitlab-ci.yaml",
        ".github/workflows",
        ".circleci/config.yml",
        "jenkinsfile",
        ".travis.yml",
        "azure-pipelines.yml",
    }
)
_DOC_ROOTS = frozenset({"docs", "doc", "documentation"})
_TEST_ROOTS = frozenset({"tests", "test", "spec", "specs", "__tests__"})

_LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".sql": "SQL",
}


class RepositoryScanner:
    """Produce a :class:`RepositorySnapshot` from a checked-out tree."""

    def scan(
        self, checkout_path: Path, repository_id: RepositoryId, revision: str
    ) -> RepositorySnapshot:
        files = sorted(
            path.relative_to(checkout_path).as_posix()
            for path in checkout_path.rglob("*")
            if path.is_file()
        )
        languages = sorted({lang for f in files if (lang := self._language(f))})
        return RepositorySnapshot(
            repository_id=repository_id,
            revision=revision,
            tree=files,
            languages=languages,
            manifest_files=[f for f in files if classify_file(f) is FileCategory.MANIFEST],
            dockerfiles=[f for f in files if Path(f).name.lower() in _DOCKERFILE_NAMES],
            compose_files=[f for f in files if Path(f).name.lower() in _COMPOSE_NAMES],
            ci_configuration=[f for f in files if self._is_ci(f)],
            documentation_roots=[self._root(f) for f in files if self._is_doc(f)],
            test_roots=[self._root(f) for f in files if self._is_test(f)],
        )

    @staticmethod
    def _language(path: str) -> str | None:
        suffix = Path(path).suffix.lower()
        return _LANGUAGE_BY_SUFFIX.get(suffix)

    @staticmethod
    def _is_ci(path: str) -> bool:
        return (
            path.lower() in _CI_PATHS
            or ".github/workflows" in path.lower()
            or ".gitlab-ci" in path.lower()
        )

    @staticmethod
    def _is_doc(path: str) -> bool:
        parts = path.lower().split("/")
        return any(part in _DOC_ROOTS for part in parts) or Path(path).suffix.lower() in {
            ".md",
            ".markdown",
            ".rst",
            ".adoc",
            ".txt",
        }

    @staticmethod
    def _is_test(path: str) -> bool:
        parts = path.lower().split("/")
        name = Path(path).name.lower()
        if any(part in _TEST_ROOTS for part in parts):
            return True
        return name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.go")

    @staticmethod
    def _root(path: str) -> str:
        parts = path.split("/")
        if len(parts) > 1:
            return parts[0]
        return path


__all__ = ["RepositoryScanner"]
