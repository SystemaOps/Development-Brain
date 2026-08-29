"""Command dispatch helpers for the API (Phase 24).

Routes build canonical command envelopes and enqueue them on the container's
command queue, returning the standard 202 ``AcceptedResult``.  This makes the
API trigger-neutral: a user request and an external event converge on the same
command semantics.
"""

from __future__ import annotations

import uuid

from brain.api.schemas import AcceptedResult
from brain.bootstrap.container import BrainContainer
from brain.domain.commands import (
    CommandEnvelope,
    CommandType,
    TriggerType,
    make_command,
)
from brain.ports.commands import CommandQueue


async def enqueue_command(
    container: BrainContainer,
    command_type: CommandType,
    model: object,
    *,
    trigger_type: TriggerType = TriggerType.USER,
    correlation_id: uuid.UUID | None = None,
) -> AcceptedResult:
    """Enqueue a canonical command and return the standard 202 result."""
    queue = container.services["command_queue"]
    assert isinstance(queue, CommandQueue)
    envelope: CommandEnvelope = make_command(
        command_type,
        model,  # type: ignore[arg-type]
        trigger_type=trigger_type,
        correlation_id=correlation_id,
    )
    await queue.enqueue(envelope)
    return AcceptedResult(
        command_id=str(envelope.command_id),
        status="ACCEPTED",
    )
