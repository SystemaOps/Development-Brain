"""SyncWatermarkRepository contract (Phase 0.6)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from brain.domain.sync_watermark import ProviderSyncWatermark
from brain.ports.sync_watermark import SyncWatermarkRepository


class SyncWatermarkRepositoryContract:
    @pytest.fixture
    def watermarks(self) -> SyncWatermarkRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, watermarks: SyncWatermarkRepository) -> None:
        assert isinstance(watermarks, SyncWatermarkRepository)

    async def test_get_or_create_returns_fresh(self, watermarks: SyncWatermarkRepository) -> None:
        watermark = await watermarks.get_or_create("openproject", "work_items:8")
        assert watermark.provider == "openproject"
        assert watermark.sync_key == "work_items:8"
        assert watermark.last_synced_at is None
        assert watermark.bootstrap_completed_at is None

    async def test_save_and_reload(self, watermarks: SyncWatermarkRepository) -> None:
        watermark = await watermarks.get_or_create("openproject", "work_items:8")
        watermark = watermark.model_copy(
            update={
                "last_synced_at": datetime.now(UTC),
                "last_external_id": "99",
                "bootstrap_completed_at": datetime.now(UTC),
            }
        )
        await watermarks.save(watermark)

        loaded = await watermarks.get_or_create("openproject", "work_items:8")
        assert loaded.last_synced_at is not None
        assert loaded.last_external_id == "99"
        assert loaded.bootstrap_completed_at is not None

    async def test_keys_are_independent(self, watermarks: SyncWatermarkRepository) -> None:
        await watermarks.save(
            ProviderSyncWatermark(
                provider="openproject",
                sync_key="work_items:8",
                last_external_id="a",
            )
        )
        other = await watermarks.get_or_create("openproject", "work_items:9")
        assert other.last_external_id is None
