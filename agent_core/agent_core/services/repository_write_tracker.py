from __future__ import annotations

from pathlib import Path

from agent_core.domain.repositories import RepositoryBinding, normalize_repository_relative_path
from agent_core.ports.repository import RepositoryPort


class RepositoryWriteTracker:
    def __init__(self, *, binding: RepositoryBinding, repository: RepositoryPort) -> None:
        self.binding = binding
        self.repository = repository
        self._resolved: dict[str, Path] = {}
        self._written: set[str] = set()

    def resolve_allowed_write(self, relative_path: str) -> Path:
        normalized = normalize_repository_relative_path(relative_path)
        absolute = Path(
            self.repository.resolve_write_path(
                repository_key=self.binding.repository_key,
                relative_path=normalized,
            )
        )
        self._resolved[normalized] = absolute
        return absolute

    def record_write(self, relative_path: str) -> None:
        normalized = normalize_repository_relative_path(relative_path)
        if normalized not in self._resolved:
            raise ValueError(f"Write was not pre-authorized: {normalized}")
        self._written.add(normalized)

    @property
    def changed_files(self) -> list[str]:
        return sorted(self._written)
