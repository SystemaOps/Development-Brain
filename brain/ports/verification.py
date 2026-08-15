"""Verification ports (Phase 13).

``CommandRunner`` runs project-configured deterministic checks (tests, lint,
format, type checks, build) and returns captured output as evidence.
``VerificationResultRepository`` persists verification runs so the PR gate and
later evaluation can inspect verdicts.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.identity import ExecutionId, VerificationId
from brain.domain.verification_plan import VerificationRun


@runtime_checkable
class CommandRunner(Protocol):
    """Runs a shell/CI command and captures its output."""

    async def run(
        self, command: str, *, workspace_path: str | None = None, timeout_seconds: int = 300
    ) -> dict[str, object]: ...


@runtime_checkable
class VerificationRunRepository(Protocol):
    async def save_run(self, run: VerificationRun) -> VerificationRun: ...

    async def get_run(self, run_id: VerificationId) -> VerificationRun | None: ...

    async def list_runs_for_execution(self, execution_id: ExecutionId) -> list[VerificationRun]: ...

    async def delete_run(self, run_id: VerificationId) -> None: ...


__all__ = ["CommandRunner", "VerificationRunRepository"]
