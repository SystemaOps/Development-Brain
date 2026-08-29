"""In-memory executor registry reference implementation."""

from __future__ import annotations

import uuid

from brain.domain.executor import ExecutorDescriptor


class InMemoryExecutorRegistry:
    """In-memory storage for executor descriptors."""

    def __init__(self) -> None:
        self._executors: dict[uuid.UUID, ExecutorDescriptor] = {}

    async def register(self, descriptor: ExecutorDescriptor) -> ExecutorDescriptor:
        self._executors[descriptor.executor_id] = descriptor
        return descriptor

    async def unregister(self, executor_id: uuid.UUID) -> None:
        self._executors.pop(executor_id, None)

    async def list(self) -> list[ExecutorDescriptor]:
        return list(self._executors.values())

    async def get(self, executor_id: uuid.UUID) -> ExecutorDescriptor | None:
        return self._executors.get(executor_id)

    async def select(
        self,
        *,
        requires_coding: bool = False,
        requires_tools: bool = False,
        min_context_window: int = 0,
        deployment: str | None = None,
    ) -> ExecutorDescriptor | None:
        for descriptor in self._executors.values():
            capabilities = descriptor.capabilities
            if requires_coding and not capabilities.coding:
                continue
            if requires_tools and not capabilities.tool_support:
                continue
            if capabilities.context_window < min_context_window:
                continue
            if deployment is not None and capabilities.deployment.value != deployment:
                continue
            return descriptor
        return None
