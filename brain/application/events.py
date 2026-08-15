"""Ingestion of normalized canonical events.

:class:`IncomingEventProcessor` is the single choke point through which
provider-normalized events enter the brain:

- external events carry an ``idempotency_key`` (provider webhook ID, commit
  SHA + event, document version ID, ...) and are deduplicated against the
  :class:`~brain.ports.idempotency.IdempotencyStore`;
- events are dispatched to subscribed handlers on the event bus;
- every processed event is appended to the event log so operational chains
  can be traced through one ``correlation_id``.

The processor only knows ports, so it is safe to use with the in-memory
reference adapters and with PostgreSQL.  Multi-entity atomicity is the
caller's concern: wrap ``process`` in a ``PostgresUnitOfWork`` when handlers
mutate durable state.
"""

from __future__ import annotations

from enum import StrEnum

from brain.domain.events import EventEnvelope
from brain.ports.event_bus import EventBus
from brain.ports.event_log import EventLogRepository
from brain.ports.idempotency import IdempotencyStore


class ProcessOutcome(StrEnum):
    PROCESSED = "processed"
    SKIPPED_ALREADY_PROCESSED = "skipped_already_processed"


class IncomingEventProcessor:
    def __init__(
        self,
        bus: EventBus,
        idempotency: IdempotencyStore,
        event_log: EventLogRepository,
    ) -> None:
        self._bus = bus
        self._idempotency = idempotency
        self._event_log = event_log

    async def process(self, envelope: EventEnvelope) -> ProcessOutcome:
        """Deliver ``envelope`` to handlers exactly once when deduplicable.

        Events without an ``idempotency_key`` are always dispatched (internal
        events may repeat legitimately).
        """
        key = envelope.idempotency_key
        if key is not None and await self._idempotency.is_processed(key):
            return ProcessOutcome.SKIPPED_ALREADY_PROCESSED

        await self._bus.publish(envelope)
        await self._event_log.append(envelope)
        if key is not None:
            await self._idempotency.mark_processed(key, event_id=envelope.event_id)
        return ProcessOutcome.PROCESSED
