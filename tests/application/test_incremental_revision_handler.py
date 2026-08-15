"""Unit tests for IncrementalRevisionHandler (Phase 4.5)."""

from __future__ import annotations

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.repositories import (
    InMemoryRepositoryChangeSetRepository,
    InMemoryRepositoryRepository,
)
from brain.application import IncrementalRevisionHandler
from brain.domain import (
    EventType,
    RepositoryRegistered,
    RepositoryRevisionChanged,
    model_to_envelope,
)
from brain.domain.identity import new_project_id, new_repository_id
from brain.domain.repositories import Repository
from brain.domain.repository_scan import FileCategory


class FakeSourceControl:
    def __init__(self, changed_files: list[str]) -> None:
        self._changed_files = changed_files

    async def register_repository(self, repository: Repository) -> None: ...

    async def clone_or_fetch(self, repository: Repository) -> None: ...

    async def get_default_branch(self, repository: Repository) -> str:
        return "main"

    async def get_current_revision(self, repository: Repository) -> str:
        return "rev"

    async def list_changed_files(
        self, repository: Repository, base_revision: str, target_revision: str
    ) -> list[str]:
        return self._changed_files

    async def read_file_at_revision(
        self, repository: Repository, path: str, revision: str
    ) -> bytes:
        return b""

    async def create_branch(
        self, repository: Repository, branch_name: str, base_revision: str
    ) -> None: ...

    async def create_worktree(
        self,
        repository: Repository,
        branch_name: str,
        base_revision: str,
        path: str,
    ) -> None: ...

    async def get_diff(
        self, repository: Repository, base_revision: str, target_revision: str
    ) -> str:
        return ""

    async def commit(self, repository: Repository, branch_name: str, message: str) -> str:
        return "new-commit"

    async def push(self, repository: Repository, branch_name: str) -> None: ...


async def test_handler_classifies_and_persists_change_set() -> None:
    repositories = InMemoryRepositoryRepository()
    change_sets = InMemoryRepositoryChangeSetRepository()
    repo = Repository(
        id=new_repository_id(),
        project_id=new_project_id(),
        name="demo",
        clone_url="unused",
    )
    await repositories.create(repo)

    handler = IncrementalRevisionHandler(
        repositories=repositories,
        source_control=FakeSourceControl(
            ["src/app.py", "docs/guide.md", "tests/test_app.py", "settings.json"]
        ),
        change_sets=change_sets,
    )
    bus = InMemoryEventBus()
    await bus.subscribe(EventType.REPOSITORY_REVISION_CHANGED.value, handler)

    envelope = model_to_envelope(
        RepositoryRevisionChanged(
            repository_id=repo.id,
            old_revision="old",
            new_revision="new",
        ),
        source="git-webhook",
        project_id=repo.project_id,
    )
    await bus.publish(envelope)

    stored = await change_sets.list_change_sets(repo.id)
    assert len(stored) == 1
    categories = {f.category for f in stored[0].files}
    assert categories == {
        FileCategory.SOURCE,
        FileCategory.DOCUMENTATION,
        FileCategory.TEST,
        FileCategory.CONFIGURATION,
    }

    updated = await repositories.get(repo.id)
    assert updated is not None
    assert updated.current_revision == "new"


async def test_handler_ignores_other_event_types() -> None:
    change_sets = InMemoryRepositoryChangeSetRepository()
    handler = IncrementalRevisionHandler(
        repositories=InMemoryRepositoryRepository(),
        source_control=FakeSourceControl([]),
        change_sets=change_sets,
    )
    bus = InMemoryEventBus()
    await bus.subscribe(EventType.REPOSITORY_REGISTERED.value, handler)

    repo = Repository(
        id=new_repository_id(),
        project_id=new_project_id(),
        name="demo",
        clone_url="unused",
    )
    envelope = model_to_envelope(
        RepositoryRegistered(repository=repo),
        source="git-webhook",
        project_id=repo.project_id,
    )
    await bus.publish(envelope)
    assert len(await change_sets.list_change_sets(repo.id)) == 0
