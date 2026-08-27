"""Redis command queue adapter (Phase 24).

Production implementation of :class:`CommandQueue` backed by Redis lists.  It
uses a main list (pending), an in-flight hash for unacknowledged commands, and
a dead-letter list.  Envelope JSON is stored so commands survive restarts.
"""

from __future__ import annotations

import json
import uuid

from redis.asyncio import Redis

from brain.domain.commands import CommandEnvelope

_PENDING_KEY = "{queue}:pending"
_INFLIGHT_KEY = "{queue}:inflight"
_DEAD_KEY = "{queue}:dead"


class RedisCommandQueue:
    """Redis-backed command queue."""

    def __init__(self, redis: Redis, *, queue_name: str = "brain:commands") -> None:
        self._redis = redis
        self._queue = queue_name
        self._pending = _PENDING_KEY.format(queue=queue_name)
        self._inflight = _INFLIGHT_KEY.format(queue=queue_name)
        self._dead = _DEAD_KEY.format(queue=queue_name)

    async def enqueue(self, command: CommandEnvelope) -> None:
        await self._redis.rpush(self._pending, command.model_dump_json())

    async def consume(self, timeout_seconds: float = 1.0) -> CommandEnvelope | None:
        raw = await self._redis.blpop(self._pending, timeout=int(timeout_seconds))
        if raw is None:
            return None
        _, value = raw
        command = CommandEnvelope.model_validate_json(value)
        await self._redis.hset(self._inflight, command.command_id.hex, value)
        return command

    async def acknowledge(self, command_id: uuid.UUID) -> None:
        await self._redis.hdel(self._inflight, command_id.hex)

    async def requeue(self, command: CommandEnvelope, *, delay_seconds: float = 0.0) -> None:
        await self._redis.hdel(self._inflight, command.command_id.hex)
        if delay_seconds > 0:
            import asyncio

            await asyncio.sleep(delay_seconds)
        await self.enqueue(command)

    async def dead_letter(self, command: CommandEnvelope, reason: str) -> None:
        await self._redis.hdel(self._inflight, command.command_id.hex)
        await self._redis.rpush(
            self._dead, json.dumps({"command": command.model_dump(mode="json"), "reason": reason})
        )

    async def pending_count(self) -> int:
        return int(await self._redis.llen(self._pending))

    async def close(self) -> None:
        await self._redis.aclose()
