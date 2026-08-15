"""Phase 3 completion gate.

A fake provider event must pass through the event system and update canonical
state idempotently:

- a normalized canonical event (with an idempotency key) is processed once;
- redelivering the same event is skipped and leaves state unchanged;
- the whole operational chain shares one ``correlation_id`` and is traceable
  through the event log;
- the flow is durable: it survives a session/engine restart on PostgreSQL.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.event_log import InMemoryEventLogRepository
from brain.adapters.in_memory.idempotency import InMemoryIdempotencyStore
from brain.adapters.in_memory.repositories import (
    InMemoryDocumentRepository,
    InMemoryExecutionRepository,
    InMemoryProjectRepository,
    InMemoryRepositoryRepository,
    InMemoryRequirementRepository,
    InMemoryWorkItemRepository,
)
from brain.adapters.postgresql.config import DatabaseSettings
from brain.adapters.postgresql.database import (
    async_session_factory,
    create_async_engine,
    create_repositories,
)
from brain.adapters.postgresql.tables import (
    Base,
    EventLogRow,
    IdempotencyKeyRow,
    WorkItemRow,
)
from brain.adapters.postgresql.unit_of_work import PostgresUnitOfWork
from brain.application import (
    CanonicalStateProjection,
    IncomingEventProcessor,
    ProcessOutcome,
)
from brain.domain import (
    EventType,
    ExecutionRequested,
    WorkItem,
    WorkItemChanged,
    derive_event,
    model_to_envelope,
)
from brain.domain.identity import ProjectId, WorkflowId, new_actor_id, new_work_item_id
from tests.conftest import TEST_DATABASE_URL, postgres_reachable

PROJECT_ID = ProjectId(uuid.uuid4())


def _fake_provider_event(idempotency_key: str, title: str = "provider ticket"):
    work_item = WorkItem(project_id=PROJECT_ID, title=title)
    return work_item, model_to_envelope(
        WorkItemChanged(work_item=work_item),
        source="fake-jira",
        project_id=PROJECT_ID,
        idempotency_key=idempotency_key,
    )


async def test_fake_provider_event_updates_state_idempotently() -> None:
    bus = InMemoryEventBus()
    idempotency = InMemoryIdempotencyStore()
    event_log = InMemoryEventLogRepository()
    work_items = InMemoryWorkItemRepository()
    processor = IncomingEventProcessor(bus, idempotency, event_log)
    projection = CanonicalStateProjection(
        projects=InMemoryProjectRepository(),
        repositories=InMemoryRepositoryRepository(),
        work_items=work_items,
        requirements=InMemoryRequirementRepository(),
        documents=InMemoryDocumentRepository(),
        executions=InMemoryExecutionRepository(),
    )
    await bus.subscribe(EventType.WORK_ITEM_CHANGED.value, projection)

    work_item, envelope = _fake_provider_event("webhook-42")

    assert await processor.process(envelope) == ProcessOutcome.PROCESSED
    stored = await work_items.get(work_item.id)
    assert stored == work_item

    assert await processor.process(envelope) == ProcessOutcome.SKIPPED_ALREADY_PROCESSED
    assert len(await work_items.list_by_project(PROJECT_ID)) == 1
    assert await work_items.get(work_item.id) == work_item

    chain = await event_log.list_by_correlation(envelope.correlation_id)
    assert len(chain) == 1


async def test_operational_chain_shares_one_correlation() -> None:
    bus = InMemoryEventBus()
    event_log = InMemoryEventLogRepository()
    processor = IncomingEventProcessor(bus, InMemoryIdempotencyStore(), event_log)

    _, parent = _fake_provider_event("webhook-7")
    derived = derive_event(
        parent,
        ExecutionRequested(execution=_execution()),
        source="ingestion",
    )

    assert derived.correlation_id == parent.correlation_id
    assert derived.causation_id == parent.event_id

    await processor.process(parent)
    await processor.process(derived)

    chain = await event_log.list_by_correlation(parent.correlation_id)
    assert [e.event_id for e in chain] == [parent.event_id, derived.event_id]
    assert chain[1].causation_id == parent.event_id


def _execution():
    from brain.domain import Execution

    return Execution(
        workflow_id=WorkflowId(uuid.uuid4()),
        work_item_id=new_work_item_id(),
        executor_id=new_actor_id(),
    )


async def test_postgres_flow_is_idempotent_and_durable() -> None:
    if not postgres_reachable(TEST_DATABASE_URL):
        pytest.skip("PostgreSQL is not available; start it with: docker compose up -d")

    engine = create_async_engine(DatabaseSettings(url=TEST_DATABASE_URL, echo=False))
    factory = async_session_factory(engine)
    work_item, envelope = _fake_provider_event("pg-webhook-1")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        work_item, envelope = _fake_provider_event("pg-webhook-1")
        bus = InMemoryEventBus()
        async with PostgresUnitOfWork(factory) as uow:
            repos = uow.repos
            processor = IncomingEventProcessor(bus, repos.idempotency, repos.event_log)
            projection = CanonicalStateProjection(
                projects=repos.projects,
                repositories=repos.repositories,
                work_items=repos.work_items,
                requirements=repos.requirements,
                documents=repos.documents,
                executions=repos.executions,
            )
            await bus.subscribe(EventType.WORK_ITEM_CHANGED.value, projection)
            assert await processor.process(envelope) == ProcessOutcome.PROCESSED
            assert await processor.process(envelope) == ProcessOutcome.SKIPPED_ALREADY_PROCESSED
            await uow.commit()

        async with factory() as session:
            repos = create_repositories(session)
            assert await repos.work_items.get(work_item.id) == work_item
            assert len(await repos.event_log.list_by_correlation(envelope.correlation_id)) == 1
    finally:
        async with factory() as session:
            await session.execute(
                delete(EventLogRow).where(EventLogRow.correlation_id == envelope.correlation_id)
            )
            await session.execute(
                delete(IdempotencyKeyRow).where(
                    IdempotencyKeyRow.idempotency_key == envelope.idempotency_key
                )
            )
            await session.execute(delete(WorkItemRow).where(WorkItemRow.id == work_item.id))
            await session.commit()
        await engine.dispose()
