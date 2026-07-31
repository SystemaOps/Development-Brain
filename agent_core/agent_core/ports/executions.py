from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from agent_core.domain.enums import AgentExecutionStatus


@dataclass(frozen=True)
class AgentExecutionStart:
    execution_id: UUID
    attempt_number: int


class AgentExecutionRecorderPort(Protocol):
    async def start(
        self,
        *,
        project_id: UUID,
        agent_name: str,
        thread_id: str,
        trigger_event_id: str | None,
        config_snapshot: dict[str, Any],
    ) -> AgentExecutionStart:
        ...

    async def finish(
        self,
        execution_id: UUID,
        *,
        status: AgentExecutionStatus,
        error_summary: dict[str, Any] | None = None,
    ) -> None:
        ...
