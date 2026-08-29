"""Runtime capability registry (Phase 22).

Implements the :class:`CapabilityRegistry` port for the composition root.  It
holds :class:`CapabilityDescriptor` entries, can refresh them through optional
:class:`HealthCheckPort` probes (Task 22.4), and evaluates readiness from
required vs optional capabilities (Task 22.3).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from brain.domain.capabilities import (
    CapabilityDescriptor,
    CapabilityHealth,
    CapabilityName,
    CapabilityStatus,
)

logger = logging.getLogger(__name__)

ProbeResult = CapabilityHealth | CapabilityStatus | bool
HealthProbe = Callable[[], ProbeResult | Awaitable[ProbeResult]]


class CapabilityRegistry:
    """In-memory registry of runtime capabilities with refresh + readiness."""

    def __init__(self) -> None:
        self._descriptors: dict[CapabilityName, CapabilityDescriptor] = {}
        self._probes: dict[CapabilityName, HealthProbe] = {}

    def register(
        self,
        descriptor: CapabilityDescriptor,
        *,
        probe: HealthProbe | None = None,
    ) -> None:
        self._descriptors[descriptor.name] = descriptor
        if probe is not None:
            self._probes[descriptor.name] = probe

    def register_health(
        self,
        name: CapabilityName,
        *,
        provider: str = "",
        required: bool = False,
        status: CapabilityStatus = CapabilityStatus.UNAVAILABLE,
        detail: str = "",
        probe: HealthProbe | None = None,
    ) -> None:
        self.register(
            CapabilityDescriptor(
                name=name,
                provider=provider,
                required=required,
                health=CapabilityHealth(status=status, detail=detail),
            ),
            probe=probe,
        )

    def get(self, name: CapabilityName) -> CapabilityDescriptor | None:
        return self._descriptors.get(name)

    def snapshot(self) -> dict[str, CapabilityDescriptor]:
        return {name.value: descriptor for name, descriptor in self._descriptors.items()}

    async def refresh(self) -> None:
        """Re-run registered health probes and update statuses (Task 22.4)."""
        for name, descriptor in list(self._descriptors.items()):
            probe = self._probes.get(name)
            if probe is None:
                continue
            health = await _run_probe(probe)
            descriptor.health = health
            logger.info("capability %s refreshed -> %s", name.value, health.status.value)

    def is_ready(self) -> bool:
        """Required capabilities must be usable (AVAILABLE/DEGRADED).

        Optional unavailable/disabled capabilities do not block readiness.
        """
        return all(
            not descriptor.required or descriptor.health.is_usable
            for descriptor in self._descriptors.values()
        )

    def ready_problems(self) -> list[str]:
        """Human-readable reasons readiness failed (or empty if ready)."""
        problems: list[str] = []
        for descriptor in self._descriptors.values():
            if descriptor.required and not descriptor.health.is_usable:
                problems.append(
                    f"{descriptor.name.value}: {descriptor.health.status.value}"
                    + (f" ({descriptor.health.detail})" if descriptor.health.detail else "")
                )
        return problems


async def _run_probe(probe: HealthProbe) -> CapabilityHealth:
    try:
        result = probe()
        if isinstance(result, Awaitable):
            result = await result
        return _to_health(result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("capability probe failed", exc_info=True)
        return CapabilityHealth(
            status=CapabilityStatus.UNAVAILABLE,
            detail=f"{type(exc).__name__}: {exc}",
        )


def _to_health(result: ProbeResult) -> CapabilityHealth:
    if isinstance(result, CapabilityHealth):
        return result
    if isinstance(result, bool):
        return CapabilityHealth(
            status=CapabilityStatus.AVAILABLE if result else CapabilityStatus.UNAVAILABLE
        )
    return CapabilityHealth(status=result)


__all__ = ["CapabilityRegistry", "HealthProbe"]
