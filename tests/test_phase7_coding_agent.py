from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_core.domain.coding import CodingAttemptRequest, FileChange, QualityCommand
from agent_core.domain.enums import CodingAttemptStatus, RepositoryAccessMode
from agent_core.domain.repositories import RepositoryBinding


def _init_git_repo(repo: Path) -> None:
    result = subprocess.run(["git", "init"], cwd=repo, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        pytest.skip("git is not available in this environment")
    subprocess.run(["git", "config", "user.email", "ada@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Ada Tests"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, capture_output=True, text=True, check=True)


@pytest.mark.asyncio
async def test_safe_command_runner_redacts_and_truncates_output(tmp_path: Path):
    from agent_core.adapters.command_runner import SafeSubprocessCommandRunner

    result = await SafeSubprocessCommandRunner(secrets=("secret-token",)).run(
        command=[sys.executable, "-c", "print('secret-token-' + 'x' * 2000)"],
        cwd=str(tmp_path),
        timeout_seconds=10,
        output_limit_bytes=128,
    )

    assert result.exit_code == 0
    assert "secret-token" not in result.stdout
    assert "[REDACTED]" in result.stdout
    assert "truncated" in result.stdout


@pytest.mark.asyncio
async def test_coding_attempt_runner_applies_allowed_write_and_quality_command(tmp_path: Path):
    from agent_core.adapters.command_runner import SafeSubprocessCommandRunner
    from agent_core.adapters.repository_filesystem import LocalRepositoryFilesystem
    from agent_core.services.coding_service import CodingAttemptRunner

    repo = tmp_path / "repo"
    src = repo / "src"
    src.mkdir(parents=True)
    (src / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
    _init_git_repo(repo)

    binding = RepositoryBinding(
        repository_key="demo-repo",
        mount_path=str(repo),
        access_mode=RepositoryAccessMode.READ_WRITE,
        write_allowlist=("src/**",),
        command_allowlist=(Path(sys.executable).name,),
    )
    request = CodingAttemptRequest(
        task_key="task.update-value",
        repository_key="demo-repo",
        file_changes=[FileChange(relative_path="src/app.py", content="VALUE = 'new'\n")],
        quality_commands=[
            QualityCommand(
                command=(sys.executable, "-c", "print('secret-token')"),
                timeout_seconds=10,
                output_limit_bytes=4096,
            )
        ],
    )

    result = await CodingAttemptRunner(
        binding=binding,
        repository=LocalRepositoryFilesystem([binding]),
        command_runner=SafeSubprocessCommandRunner(secrets=("secret-token",)),
    ).run(request=request, attempt_number=2)

    assert result.status == CodingAttemptStatus.SUCCEEDED
    assert result.attempt_number == 2
    assert result.changed_files == ["src/app.py"]
    assert result.command_results[0].stdout.strip() == "[REDACTED]"
    assert "VALUE = 'new'" in result.final_diff
    assert result.rollback_plan.available is True
    assert result.rollback_plan.strategy == "reverse_diff"


@pytest.mark.asyncio
async def test_coding_attempt_runner_blocks_write_outside_allowlist(tmp_path: Path):
    from agent_core.adapters.command_runner import SafeSubprocessCommandRunner
    from agent_core.adapters.repository_filesystem import LocalRepositoryFilesystem
    from agent_core.services.coding_service import CodingAttemptRunner

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("old\n", encoding="utf-8")
    binding = RepositoryBinding(
        repository_key="demo-repo",
        mount_path=str(repo),
        access_mode=RepositoryAccessMode.READ_WRITE,
        write_allowlist=("src/**",),
        command_allowlist=(Path(sys.executable).name,),
    )

    result = await CodingAttemptRunner(
        binding=binding,
        repository=LocalRepositoryFilesystem([binding]),
        command_runner=SafeSubprocessCommandRunner(),
    ).run(
        request=CodingAttemptRequest(
            task_key="task.bad-write",
            repository_key="demo-repo",
            file_changes=[FileChange(relative_path="README.md", content="new\n")],
        )
    )

    assert result.status == CodingAttemptStatus.BLOCKED
    assert "outside the write allowlist" in result.errors[0]
    assert (repo / "README.md").read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_coding_attempt_runner_marks_failed_quality_command(tmp_path: Path):
    from agent_core.adapters.command_runner import SafeSubprocessCommandRunner
    from agent_core.adapters.repository_filesystem import LocalRepositoryFilesystem
    from agent_core.services.coding_service import CodingAttemptRunner

    repo = tmp_path / "repo"
    src = repo / "src"
    src.mkdir(parents=True)
    (src / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
    binding = RepositoryBinding(
        repository_key="demo-repo",
        mount_path=str(repo),
        access_mode=RepositoryAccessMode.READ_WRITE,
        write_allowlist=("src/**",),
        command_allowlist=(Path(sys.executable).name,),
    )

    result = await CodingAttemptRunner(
        binding=binding,
        repository=LocalRepositoryFilesystem([binding]),
        command_runner=SafeSubprocessCommandRunner(),
    ).run(
        request=CodingAttemptRequest(
            task_key="task.quality-failure",
            repository_key="demo-repo",
            file_changes=[FileChange(relative_path="src/app.py", content="VALUE = 'new'\n")],
            quality_commands=[QualityCommand(command=(sys.executable, "-c", "import sys; sys.exit(7)"))],
        )
    )

    assert result.status == CodingAttemptStatus.FAILED
    assert result.command_results[0].exit_code == 7
    assert "Command failed" in result.errors[0]


def test_quality_command_rejects_shell_strings():
    with pytest.raises(ValidationError, match="argument arrays"):
        QualityCommand(command="pytest -q")


def test_coding_attempt_model_and_migration_contract():
    from agent_core.models import CodingAttemptRecord

    assert CodingAttemptRecord.__tablename__ == "coding_attempts"
    columns = CodingAttemptRecord.__table__.columns
    assert {
        "project_id",
        "repository_key",
        "task_key",
        "attempt_number",
        "status",
        "base_commit_sha",
        "branch",
        "changed_files",
        "command_results",
        "evidence",
        "rollback_plan",
        "final_diff",
        "error_summary",
    } <= set(columns.keys())
    assert any(
        constraint.name == "uq_coding_attempts_project_task_attempt"
        for constraint in CodingAttemptRecord.__table__.constraints
    )
    assert CodingAttemptStatus.BLOCKED.value == "blocked"
