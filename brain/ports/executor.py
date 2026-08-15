"""Executor port.

The brain never depends on a specific coding agent.  Pi, custom agents, remote
coding services, deterministic automation, and humans all implement this one
protocol and translate to/from the canonical ``ExecutionRequest`` /
``ExecutionResult``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.executions import ExecutionRequest, ExecutionResult


@runtime_checkable
class ExecutorPort(Protocol):
    async def execute(self, request: ExecutionRequest) -> ExecutionResult: ...
