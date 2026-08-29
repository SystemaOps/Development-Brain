"""OpenProject human activity adapter (Phase 27).

Publishes observations as comments/activities on the target work package and
tracks the external comment id for idempotency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from brain.domain.external_reference import ExternalReference
from brain.domain.human_activity import (
    HumanActivityReference,
    ProjectionStatus,
)
from brain.domain.observations import Observation


class OpenProjectActivityTransport(Protocol):
    """Minimal OpenProject REST surface for comments/activities."""

    async def post_comment(self, external_id: str, body: str) -> dict[str, Any]: ...


class OpenProjectActivityAdapter:
    """HumanActivityPort implementation for OpenProject."""

    def __init__(self, transport: OpenProjectActivityTransport) -> None:
        self._transport = transport

    async def publish_observation(
        self,
        target: ExternalReference,
        observation: Observation,
    ) -> HumanActivityReference:
        if target.provider != "openproject":
            return HumanActivityReference(
                observation_id=observation.id,
                provider="openproject",
                target=target,
                status=ProjectionStatus.FAILED,
                error=f"target provider mismatch: {target.provider}",
            )
        body = _format_observation(observation)
        try:
            result = await self._transport.post_comment(target.external_id, body)
            external_activity_id = str(result.get("id") or result.get("commentId") or "")
            return HumanActivityReference(
                observation_id=observation.id,
                provider="openproject",
                target=target,
                external_activity_id=external_activity_id or None,
                status=ProjectionStatus.PUBLISHED,
                published_at=datetime.now(UTC),
            )
        except Exception as exc:  # noqa: BLE001
            return HumanActivityReference(
                observation_id=observation.id,
                provider="openproject",
                target=target,
                status=ProjectionStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )


def _format_observation(observation: Observation) -> str:
    """Provider-neutral concise output (Task 27.4)."""
    lines = [
        f"Brain observation — {observation.observation_type.value.replace('_', ' ')}",
        "",
        observation.title,
    ]
    if observation.body:
        lines.append("")
        lines.append(observation.body)
    return "\n".join(lines)


__all__ = ["OpenProjectActivityAdapter", "OpenProjectActivityTransport"]
