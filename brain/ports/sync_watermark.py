"""Provider sync watermark persistence port.

Stores the durable cursor that pull reconciliation advances.  One row per
``(provider, sync_key)``; ``get_or_create`` returns a fresh watermark when no
row exists yet so callers never special-case first sync.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.sync_watermark import ProviderSyncWatermark


@runtime_checkable
class SyncWatermarkRepository(Protocol):
    async def get_or_create(self, provider: str, sync_key: str) -> ProviderSyncWatermark: ...

    async def save(self, watermark: ProviderSyncWatermark) -> ProviderSyncWatermark: ...


__all__ = ["SyncWatermarkRepository"]
