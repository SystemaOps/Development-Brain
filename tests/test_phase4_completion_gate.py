"""Phase 4 completion gate.

The brain can register a repository, identify its exact revision, detect
changes, and create an isolated worktree.  The full flow is exercised with a
real throwaway git repository and the local git adapter, then driven through
the event system (``RepositoryRevisionChanged`` -> ``IncrementalRevisionHandler``)
so the classified change set lands in canonical state.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from brain.adapters.git.local import GitError, LocalGitAdapter
from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.event_log import InMemoryEventLogRepository
from brain.adapters.in_memory.idempotency import InMemoryIdempotencyStore
from brain.adapters.in_memory.repositories import (
    InMemoryRepositoryChangeSetRepository,
    InMemoryRepositoryRepository,
)
from brain.application import (
    IncomingEventProcessor,
    IncrementalRevisionHandler,
)
from brain.domain import (
    EventType,
    RepositoryRevisionChanged,
    derive_event,
    model_to_envelope,
)
from brain.domain.identity import new_project_id, new_repository_id
from brain.domain.repositories import Repository


async def _run_git(*args: str, cwd: Path | None = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {stderr.decode(errors='replace')}")
    return stdout.decode(errors="replace").strip()


def _git_available() -> bool:
    return subprocess.run(["git", "--version"], capture_output=True).returncode == 0


async def _seed_working_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    await _run_git("init", "-b", "main", str(path))
    await _run_git("config", "user.name", "brain-test", cwd=path)
    await _run_git("config", "user.email", "brain@test.local", cwd=path)
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    (path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
    await _run_git("add", "-A", cwd=path)
    await _run_git("commit", "-m", "initial", cwd=path)
    return await _run_git("rev-parse", "HEAD", cwd=path)


@pytest.mark.asyncio
async def test_completion_gate_register_revision_changes_worktree(tmp_path: Path) -> None:
    if not _git_available():
        pytest.skip("git CLI not available")

    working = tmp_path / "work"
    base = await _seed_working_repo(working)

    adapter = LocalGitAdapter(tmp_path / "workspace")
    repo = Repository(
        id=new_repository_id(),
        project_id=new_project_id(),
        name="demo",
        clone_url=str(working),
    )

    # 1. Register and identify the exact revision.
    await adapter.register_repository(repo)
    assert await adapter.get_current_revision(repo) == base

    # 2. Detect a change.
    (working / "src" / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (working / "docs").mkdir(exist_ok=True)
    (working / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
    await _run_git("add", "-A", cwd=working)
    await _run_git("commit", "-m", "change app + docs", cwd=working)
    head = await _run_git("rev-parse", "HEAD", cwd=working)
    await adapter.clone_or_fetch(repo)

    changed = await adapter.list_changed_files(repo, base, head)
    assert "src/app.py" in changed
    assert "docs/guide.md" in changed

    # 3. Create an isolated worktree at the exact base revision.
    worktree = tmp_path / "wt-exec-42"
    await adapter.create_worktree(repo, "agent/TASK-184", base, str(worktree))
    assert await _run_git("rev-parse", "HEAD", cwd=worktree) == base
    assert (worktree / "src" / "app.py").exists()

    # 4. Drive the change through the event system.
    bus = InMemoryEventBus()
    idempotency = InMemoryIdempotencyStore()
    event_log = InMemoryEventLogRepository()
    repositories = InMemoryRepositoryRepository()
    change_sets = InMemoryRepositoryChangeSetRepository()
    handler = IncrementalRevisionHandler(
        repositories=repositories,
        source_control=adapter,
        change_sets=change_sets,
    )
    await bus.subscribe(EventType.REPOSITORY_REVISION_CHANGED.value, handler)
    processor = IncomingEventProcessor(bus, idempotency, event_log)

    await repositories.create(repo)
    envelope = model_to_envelope(
        RepositoryRevisionChanged(
            repository_id=repo.id,
            old_revision=base,
            new_revision=head,
        ),
        source="git-webhook",
        project_id=repo.project_id,
        idempotency_key=f"push-{head}",
    )
    await processor.process(envelope)

    stored = await repositories.get(repo.id)
    assert stored is not None
    assert stored.current_revision == head
    change_sets_list = await change_sets.list_change_sets(repo.id)
    assert len(change_sets_list) == 1
    paths = {f.path for f in change_sets_list[0].files}
    assert paths == {"src/app.py", "docs/guide.md"}

    # Redelivery is idempotent: no second change set is appended.
    await processor.process(envelope)
    assert len(await change_sets.list_change_sets(repo.id)) == 1


@pytest.mark.asyncio
async def test_derive_event_propagates_correlation(tmp_path: Path) -> None:
    if not _git_available():
        pytest.skip("git CLI not available")

    working = tmp_path / "work"
    base = await _seed_working_repo(working)
    adapter = LocalGitAdapter(tmp_path / "workspace")
    repo = Repository(
        id=new_repository_id(),
        project_id=new_project_id(),
        name="demo",
        clone_url=str(working),
    )
    await adapter.register_repository(repo)

    (working / "src" / "app.py").write_text("def main():\n    return 2\n", encoding="utf-8")
    await _run_git("add", "-A", cwd=working)
    await _run_git("commit", "-m", "change", cwd=working)
    head = await _run_git("rev-parse", "HEAD", cwd=working)
    await adapter.clone_or_fetch(repo)

    parent = model_to_envelope(
        RepositoryRevisionChanged(repository_id=repo.id, old_revision=base, new_revision=head),
        source="git-webhook",
        project_id=repo.project_id,
        idempotency_key=f"push-{head}",
    )
    derived = derive_event(
        parent,
        RepositoryRevisionChanged(repository_id=repo.id, old_revision=base, new_revision=head),
        source="ingestion",
    )
    assert derived.correlation_id == parent.correlation_id
    assert derived.causation_id == parent.event_id
