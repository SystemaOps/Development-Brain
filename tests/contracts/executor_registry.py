"""ExecutorRegistry contract."""

from __future__ import annotations

import pytest

from brain.domain.executor import (
    ExecutorCapabilities,
    ExecutorDescriptor,
    ExecutorKind,
)
from brain.ports.executor_registry import ExecutorRegistry


def _descriptor(name: str, **capabilities: bool | int) -> ExecutorDescriptor:
    return ExecutorDescriptor(
        name=name,
        kind=ExecutorKind.FAKE,
        capabilities=ExecutorCapabilities(**capabilities),  # type: ignore[arg-type]
    )


class ExecutorRegistryContract:
    @pytest.fixture
    def executor_registry(self) -> ExecutorRegistry:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, executor_registry: ExecutorRegistry) -> None:
        assert isinstance(executor_registry, ExecutorRegistry)

    async def test_register_and_list(self, executor_registry: ExecutorRegistry) -> None:
        descriptor = _descriptor("fake")
        await executor_registry.register(descriptor)
        descriptors = await executor_registry.list()
        assert [d.executor_id for d in descriptors] == [descriptor.executor_id]

    async def test_get(self, executor_registry: ExecutorRegistry) -> None:
        descriptor = _descriptor("fake")
        await executor_registry.register(descriptor)
        assert await executor_registry.get(descriptor.executor_id) == descriptor
        assert await executor_registry.get(descriptor.executor_id) is not None

    async def test_unregister(self, executor_registry: ExecutorRegistry) -> None:
        descriptor = _descriptor("fake")
        await executor_registry.register(descriptor)
        await executor_registry.unregister(descriptor.executor_id)
        assert await executor_registry.get(descriptor.executor_id) is None

    async def test_select_requires_coding(self, executor_registry: ExecutorRegistry) -> None:
        await executor_registry.register(
            _descriptor("non-coder", coding=False, context_window=8000)
        )
        await executor_registry.register(_descriptor("coder", coding=True, context_window=32000))
        selected = await executor_registry.select(requires_coding=True)
        assert selected is not None
        assert selected.name == "coder"

    async def test_select_min_context_window(self, executor_registry: ExecutorRegistry) -> None:
        await executor_registry.register(_descriptor("small", context_window=8000))
        selected = await executor_registry.select(min_context_window=16000)
        assert selected is None

    async def test_select_returns_none_when_no_match(
        self, executor_registry: ExecutorRegistry
    ) -> None:
        assert await executor_registry.select(requires_coding=True) is None
