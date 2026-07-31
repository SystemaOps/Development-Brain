from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.adapters.command_runner import SafeSubprocessCommandRunner
from agent_core.adapters.repository_filesystem import LocalRepositoryFilesystem
from agent_core.domain.coding import (
    CodingAttemptRequest,
    CodingAttemptResult,
    CodingAttemptStatus,
    CommandExecutionRecord,
    FileChange,
    RollbackPlan,
)
from agent_core.domain.evidence import EvidenceRef
from agent_core.domain.repositories import (
    RepositoryAccessDenied,
    RepositoryBinding,
    RepositoryPathError,
    assert_command_allowed,
)
from agent_core.models import Project
from agent_core.persistence.coding_attempts import SqlAlchemyCodingAttemptStore
from agent_core.persistence.repository_bindings import SqlAlchemyRepositoryBindingStore
from agent_core.ports.command_runner import CommandRunnerPort
from agent_core.ports.repository import RepositoryPort, RepositorySnapshot
from agent_core.services.repository_write_tracker import RepositoryWriteTracker


class CodingAttemptRunner:
    def __init__(
        self,
        *,
        binding: RepositoryBinding,
        repository: RepositoryPort,
        command_runner: CommandRunnerPort,
    ) -> None:
        self.binding = binding
        self.repository = repository
        self.command_runner = command_runner

    async def run(
        self,
        *,
        request: CodingAttemptRequest,
        attempt_number: int = 1,
    ) -> CodingAttemptResult:
        if request.repository_key != self.binding.repository_key:
            raise ValueError("Coding request repository_key does not match binding")

        errors: list[str] = []
        command_records: list[CommandExecutionRecord] = []
        evidence: list[EvidenceRef] = []
        snapshot = await _safe_snapshot(self.repository, request.repository_key)
        tracker = RepositoryWriteTracker(binding=self.binding, repository=self.repository)
        blocked = False

        try:
            for change in request.file_changes:
                await _apply_file_change(change, tracker)

            cwd = self.repository.resolve_path(
                repository_key=request.repository_key,
                relative_path=".",
            )
            for command in request.quality_commands:
                assert_command_allowed(self.binding, command.command)
                result = await self.command_runner.run(
                    command=command.command,
                    cwd=cwd,
                    timeout_seconds=command.timeout_seconds,
                    output_limit_bytes=command.output_limit_bytes,
                )
                record = CommandExecutionRecord(
                    command=result.command,
                    exit_code=result.exit_code,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    duration_seconds=result.duration_seconds,
                    timed_out=result.timed_out,
                )
                command_records.append(record)
                evidence.append(
                    EvidenceRef(
                        evidence_type="command_result",
                        uri=f"command://{request.repository_key}/{len(command_records)}",
                        title=" ".join(record.command),
                        excerpt=(record.stdout or record.stderr)[:500],
                        metadata={
                            "exit_code": record.exit_code,
                            "timed_out": record.timed_out,
                        },
                    )
                )
                if record.timed_out:
                    errors.append(f"Command timed out: {' '.join(record.command)}")
                elif record.exit_code != 0:
                    errors.append(
                        f"Command failed with exit code {record.exit_code}: {' '.join(record.command)}"
                    )
        except (RepositoryAccessDenied, RepositoryPathError) as exc:
            blocked = True
            errors.append(str(exc))
        except Exception as exc:  # pragma: no cover - exact filesystem failure is platform dependent
            errors.append(str(exc))

        final_diff = await _safe_diff(self.repository, request.repository_key)
        if final_diff:
            evidence.append(
                EvidenceRef(
                    evidence_type="repository_diff",
                    uri=f"repository://{request.repository_key}/diff",
                    title="Final repository diff",
                    excerpt=final_diff[:500],
                    metadata={"changed_files": tracker.changed_files},
                )
            )

        status = _status_from_errors(blocked=blocked, errors=errors)
        return CodingAttemptResult(
            task_key=request.task_key,
            repository_key=request.repository_key,
            attempt_number=attempt_number,
            status=status,
            base_commit_sha=snapshot.commit_sha,
            branch=snapshot.branch,
            changed_files=tracker.changed_files,
            command_results=command_records,
            final_diff=final_diff,
            rollback_plan=_rollback_plan(snapshot=snapshot, changed_files=tracker.changed_files, final_diff=final_diff),
            errors=errors,
            evidence=evidence,
        )


class CodingService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        command_runner: CommandRunnerPort | None = None,
    ) -> None:
        self.db = db
        self.binding_store = SqlAlchemyRepositoryBindingStore(db)
        self.attempt_store = SqlAlchemyCodingAttemptStore(db)
        self.command_runner = command_runner

    async def run_explicit_attempt(
        self,
        *,
        project_key: str,
        request: CodingAttemptRequest,
        secrets: list[str] | None = None,
    ) -> CodingAttemptResult:
        project = await self._get_project(project_key)
        binding = await self.binding_store.get_binding(
            project_id=project.id,
            repository_key=request.repository_key,
        )
        if binding is None:
            raise KeyError(request.repository_key)
        attempt_number = await self.attempt_store.next_attempt_number(
            project_id=project.id,
            repository_key=request.repository_key,
            task_key=request.task_key,
        )
        runner = CodingAttemptRunner(
            binding=binding,
            repository=LocalRepositoryFilesystem([binding]),
            command_runner=self.command_runner or SafeSubprocessCommandRunner(secrets=secrets or []),
        )
        result = await runner.run(request=request, attempt_number=attempt_number)
        await self.attempt_store.record_result(project_id=project.id, result=result)
        return result

    async def _get_project(self, project_key: str) -> Project:
        project = await self.db.scalar(select(Project).where(Project.project_key == project_key))
        if project is None:
            raise KeyError(project_key)
        return project


async def _apply_file_change(change: FileChange, tracker: RepositoryWriteTracker) -> None:
    path = tracker.resolve_allowed_write(change.relative_path)
    await asyncio.to_thread(path.write_text, change.content, encoding="utf-8")
    tracker.record_write(change.relative_path)


async def _safe_snapshot(repository: RepositoryPort, repository_key: str) -> RepositorySnapshot:
    try:
        return await repository.snapshot(repository_key=repository_key)
    except Exception as exc:  # pragma: no cover - git availability is environment dependent
        return RepositorySnapshot(
            repository_key=repository_key,
            commit_sha=None,
            dirty=False,
            warning=f"Repository snapshot failed: {exc}",
        )


async def _safe_diff(repository: RepositoryPort, repository_key: str) -> str:
    try:
        return await repository.diff(repository_key=repository_key)
    except Exception:
        return ""


def _status_from_errors(*, blocked: bool, errors: list[str]) -> CodingAttemptStatus:
    if blocked:
        return CodingAttemptStatus.BLOCKED
    if errors:
        return CodingAttemptStatus.FAILED
    return CodingAttemptStatus.SUCCEEDED


def _rollback_plan(
    *,
    snapshot: RepositorySnapshot,
    changed_files: list[str],
    final_diff: str,
) -> RollbackPlan:
    if not changed_files:
        return RollbackPlan(
            available=False,
            strategy="none",
            reason="No files were changed.",
            base_commit_sha=snapshot.commit_sha,
        )
    if not final_diff:
        return RollbackPlan(
            available=False,
            strategy="none",
            reason="No diff was available to reverse.",
            base_commit_sha=snapshot.commit_sha,
            changed_files=changed_files,
        )
    return RollbackPlan(
        available=True,
        strategy="reverse_diff",
        reason="Apply the recorded reverse diff under explicit rollback approval.",
        base_commit_sha=snapshot.commit_sha,
        changed_files=changed_files,
        reverse_diff=final_diff,
    )
