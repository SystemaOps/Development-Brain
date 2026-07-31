from __future__ import annotations

from typing import Protocol
from uuid import UUID

from agent_core.domain.coding import CodingAttemptResult


class CodingAttemptStorePort(Protocol):
    async def next_attempt_number(
        self,
        *,
        project_id: UUID,
        repository_key: str,
        task_key: str,
    ) -> int:
        ...

    async def record_result(
        self,
        *,
        project_id: UUID,
        result: CodingAttemptResult,
    ) -> UUID:
        ...
