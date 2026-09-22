"""Phase 1 gate: the event→command ingestion chain is wired (docs/eventbus/PLAN.md).

- ``container.incoming_events`` is an IncomingEventProcessor
- canonical events dispatched on the bus reach the CanonicalStateProjection
- dedup skips a second event with the same idempotency key
- processed events are appended to the event log
"""

from __future__ import annotations

import uuid

import pytest

from brain.api.app import create_app
from brain.application.events import IncomingEventProcessor, ProcessOutcome
from brain.bootstrap.settings import (
    BrainSettings,
    DocumentationSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    SecuritySettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)
from brain.domain.events import EventEnvelope, EventType
from brain.domain.work_items import WorkItem
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


def _settings() -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://127.0.0.1:7687"),
        storage_semantic=WeaviateSettings(host="127.0.0.1"),
        storage_queue=RedisSettings(url="redis://127.0.0.1:6379/0", provider="inmemory"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
        security=SecuritySettings(webhook_openproject_secret="op-secret"),
    )


async def test_container_exposes_incoming_event_processor() -> None:
    """1.1: the composition root wires IncomingEventProcessor."""
    app = create_app(_settings())
    async with app.router.lifespan_context(app):
        container = app.state.container
        processor = container.incoming_events
        assert isinstance(processor, IncomingEventProcessor)


async def test_processed_event_reaches_projection_handler() -> None:
    """1.2: a WORK_ITEM_CREATED event upserts the work item via projection."""
    app = create_app(_settings())
    async with app.router.lifespan_context(app):
        container = app.state.container
        project = await container.repositories.projects.create(
            __import__("brain.domain.projects", fromlist=["Project"]).Project(name="chain-test")
        )
        work_item = WorkItem(project_id=project.id, title="Chain event")
        envelope = EventEnvelope(
            event_type=EventType.WORK_ITEM_CREATED,
            source="test",
            idempotency_key=f"chain-{uuid.uuid4()}",
            payload={"work_item": work_item.model_dump(mode="json")},
        )
        outcome = await container.incoming_events.process(envelope)
        assert outcome == ProcessOutcome.PROCESSED
        persisted = await container.repositories.work_items.get(work_item.id)
        assert persisted is not None
        assert persisted.title == "Chain event"


async def test_duplicate_idempotency_key_is_skipped() -> None:
    """The processor dedupes events carrying the same idempotency key."""
    app = create_app(_settings())
    async with app.router.lifespan_context(app):
        container = app.state.container
        project = await container.repositories.projects.create(
            __import__("brain.domain.projects", fromlist=["Project"]).Project(name="dup-test")
        )
        key = f"dedup-{uuid.uuid4()}"
        envelope = EventEnvelope(
            event_type=EventType.WORK_ITEM_CREATED,
            source="test",
            idempotency_key=key,
            payload={
                "work_item": WorkItem(project_id=project.id, title="Dup").model_dump(mode="json")
            },
        )
        first = await container.incoming_events.process(envelope)
        second = await container.incoming_events.process(envelope)
        assert first == ProcessOutcome.PROCESSED
        assert second == ProcessOutcome.SKIPPED_ALREADY_PROCESSED


async def test_processed_events_are_logged() -> None:
    """Every processed event lands in the event log for traceability."""
    app = create_app(_settings())
    async with app.router.lifespan_context(app):
        container = app.state.container
        correlation_id = uuid.uuid4()
        envelope = EventEnvelope(
            event_type=EventType.DOCUMENT_CHANGED,
            source="test",
            correlation_id=correlation_id,
            payload={"document": {}},
        )
        await container.incoming_events.process(envelope)
        logged = await container.repositories.event_log.list_by_correlation(correlation_id)
        assert any(e.event_id == envelope.event_id for e in logged)


async def test_webhook_publishes_typed_work_item_events() -> None:
    """Phase 2.1: the webhook emits typed canonical events on the bus."""
    import json

    import httpx

    from brain.domain.event_types import WorkItemCreated

    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    payload = {
        "action": "work_package:created",
        "work_package": {
            "id": "43",
            "subject": "test",
            "description": {"format": "markdown", "raw": "Description", "html": ""},
            "_embedded": {
                "type": {"id": 1, "name": "Task"},
                "priority": {"id": 8, "name": "High"},
                "status": {"id": 1, "name": "New", "isClosed": False},
                "project": {"id": 8, "name": "Infrastructure"},
                "assignee": {"id": "6", "name": "brain brain"},
            },
        },
    }
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        await app_container.repositories.projects.create(
            __import__("brain.domain.projects", fromlist=["Project"]).Project(name="typed-test")
        )
        body = json.dumps(payload).encode("utf-8")
        import hashlib
        import hmac

        signature = "sha1=" + hmac.new(b"op-secret", body, hashlib.sha1).hexdigest()
        response = await client.post(
            "/api/v1/webhooks/openproject",
            content=body,
            headers={"x-op-signature": signature},
        )
        assert response.status_code == 200
        assert response.json()["event_type"] == "work_item_created"
        # A typed WorkItemCreated envelope reached the bus.
        typed = [
            e
            for e in app_container.event_bus.published
            if e.event_type == EventType.WORK_ITEM_CREATED
        ]
        assert len(typed) == 1
        envelope = typed[0]
        # Round-trips to the typed model with the canonical work item.
        from brain.domain.event_types import event_to_model

        model = event_to_model(envelope)
        assert isinstance(model, WorkItemCreated)
        assert model.work_item.title == "test"
        # The route resolves the first canonical project for the work item.
        assert any(
            p.id == model.work_item.project_id
            for p in await app_container.repositories.projects.list()
        )
        # Semantic changes and provider snapshot ride along in the payload.
        assert envelope.payload["changes"] == []
        assert envelope.payload["snapshot"]["priority"] == "High"


async def test_assignment_emits_work_item_assigned_event() -> None:
    """Phase 2.2: assignee->brain emits a typed WorkItemAssigned event."""
    import json

    import httpx

    from brain.domain.event_types import WorkItemAssigned, event_to_model

    settings = _settings()
    settings.work_management = __import__(
        "brain.bootstrap.settings", fromlist=["WorkManagementSettings"]
    ).WorkManagementSettings(
        enabled=False,
        provider="openproject",
        base_url="http://127.0.0.1:8081",
        api_key="key",
        project_id=str(uuid.uuid4()),
        brain_actor_id="6",
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    payload = {
        "action": "work_package:created",
        "work_package": {
            "id": "43",
            "subject": "test",
            "_embedded": {
                "assignee": {"id": "6", "name": "brain brain"},
            },
        },
    }
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        await app_container.repositories.projects.create(
            __import__("brain.domain.projects", fromlist=["Project"]).Project(name="assign-test")
        )
        body = json.dumps(payload).encode("utf-8")
        import hashlib
        import hmac

        signature = "sha1=" + hmac.new(b"op-secret", body, hashlib.sha1).hexdigest()
        response = await client.post(
            "/api/v1/webhooks/openproject",
            content=body,
            headers={"x-op-signature": signature},
        )
        assert response.status_code == 200
        assert response.json()["triggered"] == "assignment"
        assigned = [
            e
            for e in app_container.event_bus.published
            if e.event_type == EventType.WORK_ITEM_ASSIGNED
        ]
        assert len(assigned) == 1
        model = event_to_model(assigned[0])
        assert isinstance(model, WorkItemAssigned)
        assert model.external_actor_id == "6"
