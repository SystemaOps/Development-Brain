"""Tests for LocalGitAdapter and RepositoryScanner.

These spin up throwaway git repositories on disk (git CLI is required) and
exercise the SourceControlPort contract end-to-end: register/clone, exact
revision, changed-file detection, revision-aware reads, and isolated
worktrees.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from brain.adapters.git.local import GitError, LocalGitAdapter
from brain.adapters.git.scanner import RepositoryScanner
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


@pytest.fixture
def git_available() -> bool:
    return subprocess.run(["git", "--version"], capture_output=True).returncode == 0


@pytest.fixture
async def origin_repo(tmp_path: Path) -> AsyncIterator[Path]:
    """A bare git repository usable as a clone origin."""
    bare = tmp_path / "origin"
    bare.mkdir()
    await _run_git("init", "--bare", "-b", "main", str(bare))
    yield bare


async def _seed_repo(path: Path) -> str:
    """Create a working repo at ``path`` and return its HEAD revision."""
    path.mkdir(parents=True, exist_ok=True)
    await _run_git("init", "-b", "main", str(path))
    await _run_git("config", "user.name", "brain-test", cwd=path)
    await _run_git("config", "user.email", "brain@test.local", cwd=path)
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
    await _run_git("add", "-A", cwd=path)
    await _run_git("commit", "-m", "initial", cwd=path)
    return await _run_git("rev-parse", "HEAD", cwd=path)


def _repository(clone_url: str) -> Repository:
    return Repository(
        id=new_repository_id(),
        project_id=new_project_id(),
        name="demo",
        clone_url=clone_url,
        default_branch="main",
    )


@pytest.mark.asyncio
async def test_register_repository_and_read_revision(tmp_path: Path, git_available: bool) -> None:
    if not git_available:
        pytest.skip("git CLI not available")
    origin = tmp_path / "origin"
    origin.mkdir()
    await _run_git("init", "-b", "main", str(origin))
    await _run_git("config", "user.name", "brain-test", cwd=origin)
    await _run_git("config", "user.email", "brain@test.local", cwd=origin)
    (origin / "app.py").write_text("print('hi')\n", encoding="utf-8")
    await _run_git("add", "-A", cwd=origin)
    await _run_git("commit", "-m", "init", cwd=origin)
    head = await _run_git("rev-parse", "HEAD", cwd=origin)

    adapter = LocalGitAdapter(tmp_path / "workspace")
    repo = _repository(str(origin))
    await adapter.register_repository(repo)
    assert await adapter.get_current_revision(repo) == head


@pytest.mark.asyncio
async def test_list_changed_files_and_diff(tmp_path: Path, git_available: bool) -> None:
    if not git_available:
        pytest.skip("git CLI not available")
    working = tmp_path / "work"
    base = await _seed_repo(working)
    (working / "src" / "new.py").write_text("x = 1\n", encoding="utf-8")
    await _run_git("add", "-A", cwd=working)
    await _run_git("commit", "-m", "add new", cwd=working)
    head = await _run_git("rev-parse", "HEAD", cwd=working)

    adapter = LocalGitAdapter(tmp_path / "workspace")
    repo = _repository(str(working))
    await adapter.register_repository(repo)
    changed = await adapter.list_changed_files(repo, base, head)
    assert "src/new.py" in changed
    assert "README.md" not in changed
    diff = await adapter.get_diff(repo, base, head)
    assert "src/new.py" in diff


@pytest.mark.asyncio
async def test_read_file_at_revision(tmp_path: Path, git_available: bool) -> None:
    if not git_available:
        pytest.skip("git CLI not available")
    working = tmp_path / "work"
    base = await _seed_repo(working)
    (working / "src" / "app.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    await _run_git("add", "-A", cwd=working)
    await _run_git("commit", "-m", "change app", cwd=working)
    head = await _run_git("rev-parse", "HEAD", cwd=working)

    adapter = LocalGitAdapter(tmp_path / "workspace")
    repo = _repository(str(working))
    await adapter.register_repository(repo)
    assert b"return 42" in await adapter.read_file_at_revision(repo, "src/app.py", head)
    assert b"pass" in await adapter.read_file_at_revision(repo, "src/app.py", base)


@pytest.mark.asyncio
async def test_create_worktree_is_isolated(tmp_path: Path, git_available: bool) -> None:
    if not git_available:
        pytest.skip("git CLI not available")
    working = tmp_path / "work"
    base = await _seed_repo(working)

    adapter = LocalGitAdapter(tmp_path / "workspace")
    repo = _repository(str(working))
    await adapter.register_repository(repo)

    worktree = tmp_path / "wt-agent-184"
    await adapter.create_worktree(repo, "agent/TASK-184", base, str(worktree))
    assert (worktree / "src" / "app.py").exists()
    head = await _run_git("rev-parse", "HEAD", cwd=worktree)
    assert head == base
    branch = await _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=worktree)
    assert branch == "agent/TASK-184"


@pytest.mark.asyncio
async def test_commit_and_push_in_worktree(tmp_path: Path, git_available: bool) -> None:
    if not git_available:
        pytest.skip("git CLI not available")
    working = tmp_path / "work"
    base = await _seed_repo(working)

    adapter = LocalGitAdapter(tmp_path / "workspace")
    repo = _repository(str(working))
    await adapter.register_repository(repo)

    worktree = tmp_path / "wt-agent-200"
    await adapter.create_worktree(repo, "agent/TASK-200", base, str(worktree))
    (worktree / "src" / "app.py").write_text("def main():\n    return 7\n", encoding="utf-8")
    await _run_git("config", "user.name", "brain-test", cwd=worktree)
    await _run_git("config", "user.email", "brain@test.local", cwd=worktree)

    commit_sha = await adapter.commit(repo, "agent/TASK-200", "implement task")
    await adapter.push(repo, "agent/TASK-200")

    # The pushed commit is reachable from the origin repository.
    assert "agent/TASK-200" in await _run_git("branch", "--contains", commit_sha, cwd=working)
    assert "agent/TASK-200" in await _run_git("branch", "--all", cwd=working)


@pytest.mark.asyncio
async def test_get_default_branch(tmp_path: Path, git_available: bool) -> None:
    if not git_available:
        pytest.skip("git CLI not available")
    working = tmp_path / "work"
    await _seed_repo(working)
    adapter = LocalGitAdapter(tmp_path / "workspace")
    repo = _repository(str(working))
    await adapter.register_repository(repo)
    assert await adapter.get_default_branch(repo) == "main"


@pytest.mark.asyncio
async def test_scanner_produces_snapshot(tmp_path: Path, git_available: bool) -> None:
    if not git_available:
        pytest.skip("git CLI not available")
    working = tmp_path / "work"
    revision = await _seed_repo(working)
    (working / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (working / "tests").mkdir()
    (working / "tests" / "test_app.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (working / "docs").mkdir()
    (working / "docs" / "architecture.md").write_text("# arch\n", encoding="utf-8")

    scanner = RepositoryScanner()
    snapshot = scanner.scan(working, new_repository_id(), revision)
    assert "Python" in snapshot.languages
    assert "pyproject.toml" in snapshot.manifest_files
    assert "docs" in snapshot.documentation_roots
    assert "tests" in snapshot.test_roots
    assert "src/app.py" in snapshot.tree
    assert "README.md" in snapshot.tree


@pytest.mark.asyncio
async def test_fetch_after_new_commit(tmp_path: Path, git_available: bool) -> None:
    if not git_available:
        pytest.skip("git CLI not available")
    working = tmp_path / "work"
    base = await _seed_repo(working)
    adapter = LocalGitAdapter(tmp_path / "workspace")
    repo = _repository(str(working))
    await adapter.register_repository(repo)

    (working / "src" / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    await _run_git("add", "-A", cwd=working)
    await _run_git("commit", "-m", "change", cwd=working)
    head = await _run_git("rev-parse", "HEAD", cwd=working)

    await adapter.clone_or_fetch(repo)
    assert await adapter.get_current_revision(repo) == head
    changed = await adapter.list_changed_files(repo, base, head)
    assert changed == ["src/app.py"]
