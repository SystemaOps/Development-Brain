from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent_core.agent_platform.runtime.execution_context import CheckpointIdentity


@runtime_checkable
class CheckpointStore(Protocol):
    async def save(self, *, identity: CheckpointIdentity, state: Any) -> str:
        ...

    async def load(self, *, identity: CheckpointIdentity) -> Any | None:
        ...


class InMemoryCheckpointStore(CheckpointStore):
    def __init__(self) -> None:
        self._items: dict[tuple[tuple[str, str, str, str], str], Any] = {}

    async def save(self, *, identity: CheckpointIdentity, state: Any) -> str:
        self._items[(identity.namespace, identity.key)] = state
        return identity.checkpoint_id

    async def load(self, *, identity: CheckpointIdentity) -> Any | None:
        return self._items.get((identity.namespace, identity.key))

    def namespaces(self) -> set[tuple[str, str, str, str]]:
        return {namespace for namespace, _ in self._items}
