"""Phase D golden tests: OpenProject webhook route against real payloads.

Uses the fixtures extracted from ``docs/webhook/data.txt`` and sends them
through the signed ASGI endpoint, asserting the refactored flow:
action dispatch, snapshot diff, semantic changes, assignment gating,
project and attachment handling.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from pathlib import Path

import httpx
import pytest

from brain.api.app import create_app
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
from brain.domain.projects import Project
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)

FIXTURES = Path(__file__).parent / "fixtures" / "openproject"


async def _clean_openproject_state(container: object) -> None:
    """Remove committed provider state so fixtures diff against a clean base.

    The shared development database accumulates committed rows from live
    demos/worker runs; the webhook fixtures use fixed external ids (43, 40,
    99) and must start from an empty snapshot baseline.
    """
    from sqlalchemy import delete

    from brain.adapters.postgresql.tables import OpenProjectSnapshotRow

    session = container.session  # type: ignore[attr-defined]
    if session is not None:
        await session.execute(delete(OpenProjectSnapshotRow))
        await session.commit()


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _sign(payload: dict[str, object], secret: str) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode("utf-8")
    signature = "sha1=" + hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    return body, {"x-op-signature": signature}


def _settings(
    work_management: WorkManagementSettings | None = None,
    security: SecuritySettings | None = None,
) -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
        storage_semantic=WeaviateSettings(host="localhost"),
        storage_queue=RedisSettings(url="redis://localhost:6379/0", provider="inmemory"),
        work_management=work_management or WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
        security=security or SecuritySettings(webhook_openproject_secret="op-secret"),
    )


async def _post(client: httpx.AsyncClient, payload: dict[str, object]) -> httpx.Response:
    body, headers = _sign(payload, "op-secret")
    return await client.post("/api/v1/webhooks/openproject", content=body, headers=headers)


async def _create_project(app_container: object) -> None:
    project = Project(name="op-route-test")
    await app_container.repositories.projects.create(project)  # type: ignore[attr-defined]


async def test_created_work_package_accepted_and_snapshot_saved() -> None:
    """work_package:created → accepted, WORK_ITEM_CREATED, snapshot stored."""
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        await _clean_openproject_state(app_container)
        await _create_project(app_container)

        response = await _post(client, _load("line30_work_package_created.json"))
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] is True
        assert body["event_type"] == "work_item_created"
        assert body["external_id"] == "43"
        assert body["changes"] == []
        # No assignment trigger: assignee is absent in the created payload.
        assert "triggered" not in body
        # Snapshot persisted for the next webhook to diff against.
        snapshot = await app_container.openproject_snapshots.get("43")
        assert snapshot is not None
        assert snapshot.summary == "test"
        assert snapshot.assignee_id is None


async def test_updated_work_package_reports_semantic_changes() -> None:
    """created (no assignee) then updated (assigned) → ASSIGNEE_CHANGED."""
    brain_actor = "6"
    settings = _settings(
        WorkManagementSettings(
            enabled=False,
            provider="openproject",
            base_url="http://localhost:8081",
            api_key="key",
            project_id=str(uuid.uuid4()),
            brain_actor_id=brain_actor,
        )
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        await _clean_openproject_state(app_container)
        await _create_project(app_container)

        first = await _post(client, _load("line30_work_package_created.json"))
        assert first.status_code == 200
        assert first.json()["changes"] == []

        second = await _post(client, _load("line2_work_package_updated.json"))
        assert second.status_code == 200
        body = second.json()
        assert body["event_type"] == "work_item_changed"
        assert "assignee_changed" in body["changes"]
        # The webhook reports the assignment fact; the WorkItemAssignedHandler
        # enqueues the run command.
        assert body["triggered"] == "assignment"
        assert any(
            e.event_type.value == "work_item_assigned" for e in app_container.event_bus.published
        )
        queue = app_container.services["command_queue"]
        from brain.ports.commands import CommandQueue

        assert isinstance(queue, CommandQueue)
        pending = await queue.pending_count()
        assert pending >= 1


async def test_bare_update_without_assignee_change_triggers_nothing() -> None:
    """Doc §6: never trigger coding merely because the webhook is updated."""
    settings = _settings(
        WorkManagementSettings(
            enabled=False,
            provider="openproject",
            base_url="http://localhost:8081",
            api_key="key",
            project_id=str(uuid.uuid4()),
            brain_actor_id="6",
        )
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        await _clean_openproject_state(app_container)
        await _create_project(app_container)

        # wp 40 is already assigned to brain (6); sending the same snapshot
        # twice must not enqueue anything the second time.
        first = await _post(client, _load("line33_work_package_updated.json"))
        assert first.status_code == 200
        assert first.json()["changes"] == []
        assert "triggered" not in first.json()

        second = await _post(client, _load("line33_work_package_updated.json"))
        assert second.status_code == 200
        assert second.json()["changes"] == []
        assert "triggered" not in second.json()


async def test_project_created_publishes_project_changed() -> None:
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        await _clean_openproject_state(app_container)
        await _create_project(app_container)

        response = await _post(client, _load("line14_project_created.json"))
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] is True
        assert body["event_type"] == "project_changed"
        assert body["external_id"] == "7"
        assert any(
            e.event_type.value == "project_changed" for e in app_container.event_bus.published
        )


async def test_subproject_created_keeps_parent_id() -> None:
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        await _clean_openproject_state(app_container)
        await _create_project(app_container)

        response = await _post(client, _load("line17_project_created.json"))
        assert response.status_code == 200
        envelope = app_container.event_bus.published[-1]
        assert envelope.payload["external_id"] == "8"
        assert envelope.payload["parent_id"] == "4"


async def test_attachment_created_publishes_attachment_event() -> None:
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        await _clean_openproject_state(app_container)
        await _create_project(app_container)

        response = await _post(client, _load("line20_attachment_created.json"))
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] is True
        assert body["event_type"] == "attachment_created"
        assert body["external_id"] == "3"
        assert body["work_item_id"] == "43"
        assert any(
            e.event_type.value == "attachment_created" for e in app_container.event_bus.published
        )


async def test_unknown_action_is_ignored() -> None:
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        await _create_project(app.state.container)
        response = await _post(client, {"action": "something:else"})
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] is True
        assert body["event_type"] == "ignored"


async def test_missing_action_rejected() -> None:
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        await _create_project(app.state.container)
        response = await _post(client, {"foo": "bar"})
        assert response.status_code == 200
        assert response.json()["accepted"] is False


async def test_comment_normalization_still_works() -> None:
    """A comment activity still normalizes to HumanFeedbackReceived."""
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        await _clean_openproject_state(app_container)
        await _create_project(app_container)

        payload = {
            "action": "work_package:updated",
            "work_package": {"id": "99", "subject": "Task"},
            "comment": {
                "id": "c-1",
                "raw": "Please clarify the lockout policy.",
                "author": {"name": "alice"},
            },
        }
        response = await _post(client, payload)
        assert response.status_code == 200
        body = response.json()
        assert body["feedback"]["normalized_to"] == "HumanFeedbackReceived"
        # The canonical work item is resolved before comment normalization,
        # so the feedback carries the work item id.
        assert body["feedback"]["work_item_id"] is not None
        assert any(
            e.event_type.value == "human_feedback_received"
            for e in app_container.event_bus.published
        )
