from __future__ import annotations

from typing import Any


class RedisEventQueue:
    def __init__(self, client: Any, queue_name: str):
        self.client = client
        self.queue_name = queue_name

    @classmethod
    def from_url(cls, redis_url: str, queue_name: str) -> "RedisEventQueue":
        import redis.asyncio as redis

        return cls(
            client=redis.Redis.from_url(redis_url, decode_responses=True),
            queue_name=queue_name,
        )

    async def enqueue(self, event_id: str) -> None:
        await self.client.lpush(self.queue_name, event_id)

    async def dequeue(self, *, timeout_seconds: int = 5) -> str | None:
        item = await self.client.brpop(self.queue_name, timeout=timeout_seconds)
        if item is None:
            return None

        if isinstance(item, tuple):
            _, event_id = item
        else:
            event_id = item

        if isinstance(event_id, bytes):
            return event_id.decode("utf-8")
        return str(event_id)
