"""IdempotencyStore contract."""

from __future__ import annotations

import uuid

import pytest

from brain.ports.idempotency import IdempotencyStore


class IdempotencyStoreContract:
    @pytest.fixture
    def idempotency(self) -> IdempotencyStore:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, idempotency: IdempotencyStore) -> None:
        assert isinstance(idempotency, IdempotencyStore)

    async def test_fresh_key_is_not_processed(self, idempotency: IdempotencyStore) -> None:
        assert await idempotency.is_processed("fresh-key") is False

    async def test_marked_key_is_processed(self, idempotency: IdempotencyStore) -> None:
        await idempotency.mark_processed("webhook-1", event_id=uuid.uuid4())
        assert await idempotency.is_processed("webhook-1") is True

    async def test_keys_are_independent(self, idempotency: IdempotencyStore) -> None:
        await idempotency.mark_processed("key-a")
        assert await idempotency.is_processed("key-a") is True
        assert await idempotency.is_processed("key-b") is False

    async def test_marking_same_key_twice_is_safe(self, idempotency: IdempotencyStore) -> None:
        await idempotency.mark_processed("dup")
        await idempotency.mark_processed("dup")
        assert await idempotency.is_processed("dup") is True
