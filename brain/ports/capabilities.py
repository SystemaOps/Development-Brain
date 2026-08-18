"""Capability and health ports (Phase 22).

``HealthCheckPort`` lets adapters report their own health; the runtime's
capability registry uses it to refresh capability states.  ``CapabilityRegistry``
is the port the API / scheduler query to explain which capabilities are usable.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.capabilities import (
    CapabilityDescriptor,
    CapabilityHealth,
    CapabilityName,
)


@runtime_checkable
class HealthCheckPort(Protocol):
    """A probe that reports a capability's current health."""

    async def health(self) -> CapabilityHealth: ...


@runtime_checkable
class CapabilityRegistry(Protocol):
    def register(self, descriptor: CapabilityDescriptor) -> None: ...

    def get(self, name: CapabilityName) -> CapabilityDescriptor | None: ...

    def snapshot(self) -> dict[str, CapabilityDescriptor]: ...

    async def refresh(self) -> None: ...

    def is_ready(self) -> bool: ...


__all__ = ["CapabilityRegistry", "HealthCheckPort"]
