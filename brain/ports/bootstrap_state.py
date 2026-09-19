"""Provider bootstrap state persistence port.

Durable progress of an existing-provider bootstrap import so an interrupted
bootstrap can resume from its last checkpoint (stage + page cursor) or restart
idempotently.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.bootstrap_state import ProviderBootstrapState
from brain.domain.identity import ProjectId


@runtime_checkable
class BootstrapStateRepository(Protocol):
    async def get(self, project_id: ProjectId, provider: str) -> ProviderBootstrapState | None: ...

    async def save(self, state: ProviderBootstrapState) -> ProviderBootstrapState: ...


__all__ = ["BootstrapStateRepository"]
