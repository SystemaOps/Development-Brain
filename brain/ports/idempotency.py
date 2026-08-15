"""Idempotency store port.

External (provider) events carry an ``idempotency_key`` (provider webhook ID,
commit SHA + event, document version ID, ...).  The brain records processed
keys so that redelivered events do not double-apply to canonical state.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable


@runtime_checkable
class IdempotencyStore(Protocol):
    async def is_processed(self, key: str) -> bool: ...

    async def mark_processed(self, key: str, event_id: uuid.UUID | None = None) -> None: ...
