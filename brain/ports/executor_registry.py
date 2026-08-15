"""Executor registry port (Phase 12).

Lets the brain list available executors, register new ones, and select an
executor matching the task's capability needs.  Pi, fake executors, and custom
agents all register here; the core only ever sees :class:`ExecutorDescriptor`.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from brain.domain.executor import ExecutorCapabilities, ExecutorDescriptor


@runtime_checkable
class ExecutorRegistry(Protocol):
    async def register(self, descriptor: ExecutorDescriptor) -> ExecutorDescriptor: ...

    async def unregister(self, executor_id: uuid.UUID) -> None: ...

    async def list(self) -> list[ExecutorDescriptor]: ...

    async def get(self, executor_id: uuid.UUID) -> ExecutorDescriptor | None: ...

    async def select(
        self,
        *,
        requires_coding: bool = False,
        requires_tools: bool = False,
        min_context_window: int = 0,
        deployment: str | None = None,
    ) -> ExecutorDescriptor | None: ...


__all__ = ["ExecutorRegistry", "ExecutorCapabilities"]
