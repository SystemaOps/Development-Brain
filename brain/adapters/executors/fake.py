"""Deterministic fake executor (Task 12.5).

A deterministic implementation of :class:`ExecutorPort` for end-to-end tests:
it records the request it received and returns a configurable
:class:`ExecutionResult` without touching a real coding agent.
"""

from __future__ import annotations

from brain.domain.executions import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
)


class FakeExecutor:
    """Configurable, deterministic executor for tests."""

    def __init__(
        self,
        *,
        status: ExecutionStatus = ExecutionStatus.COMPLETED,
        modified_files: list[str] | None = None,
        observations: list[str] | None = None,
        blockers: list[str] | None = None,
    ) -> None:
        self._status = status
        self._modified_files = modified_files or []
        self._observations = observations or []
        self._blockers = blockers or []
        self.received_requests: list[ExecutionRequest] = []

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.received_requests.append(request)
        return ExecutionResult(
            execution_id=request.execution_id,
            status=self._status,
            modified_files=list(self._modified_files),
            commands_executed=["fake"],
            tests_executed=["test_login"],
            diff="diff --git a/app/login.py b/app/login.py",
            observations=list(self._observations),
            blockers=list(self._blockers),
        )


__all__ = ["FakeExecutor"]
