"""Jira human activity adapter skeleton (Phase 27).

Proves the HumanActivityPort is interchangeable: same contract, same
formatter, different provider transport.
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


class JiraActivityTransport(Protocol):
    """Minimal Jira REST surface for comments."""

    async def add_comment(self, issue_key: str, body: str) -> dict[str, Any]: ...


class JiraActivityAdapter:
    """HumanActivityPort implementation for Jira."""

    def __init__(self, transport: JiraActivityTransport) -> None:
        self._transport = transport

    async def publish_observation(
        self,
        target: ExternalReference,
        observation: Observation,
    ) -> HumanActivityReference:
        if target.provider != "jira":
            return HumanActivityReference(
                observation_id=observation.id,
                provider="jira",
                target=target,
                status=ProjectionStatus.FAILED,
                error=f"target provider mismatch: {target.provider}",
            )
        body = _format_observation(observation)
        try:
            result = await self._transport.add_comment(target.external_id, body)
            external_activity_id = str(result.get("id") or result.get("commentId") or "")
            return HumanActivityReference(
                observation_id=observation.id,
                provider="jira",
                target=target,
                external_activity_id=external_activity_id or None,
                status=ProjectionStatus.PUBLISHED,
                published_at=datetime.now(UTC),
            )
        except Exception as exc:  # noqa: BLE001
            return HumanActivityReference(
                observation_id=observation.id,
                provider="jira",
                target=target,
                status=ProjectionStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )


def _format_observation(observation: Observation) -> str:
    """Reuse the same provider-neutral format as OpenProject."""
    lines = [
        f"Brain observation — {observation.observation_type.value.replace('_', ' ')}",
        "",
        observation.title,
    ]
    if observation.body:
        lines.append("")
        lines.append(observation.body)
    return "\n".join(lines)


__all__ = ["JiraActivityAdapter", "JiraActivityTransport"]
