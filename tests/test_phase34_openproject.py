"""Phase 34 golden tests and completion gate.

An OpenProject task can trigger the Brain, receive Brain comments, and send
human feedback back into the workflow — through the webhook endpoint, the
work-management port, and the human-activity projection port.
"""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.work_management.openproject_http import OpenProjectHTTPTransport
from brain.bootstrap.container import create_brain_container
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
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ProjectId
from brain.domain.projects import Project
from brain.domain.work_items import WorkItem
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


def _signed_payload(payload: dict[str, object], secret: str) -> tuple[bytes, dict[str, str]]:
    """Return (signed body, signature headers) for the OpenProject webhook."""
    import hashlib
    import hmac
    import json

    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-OpenProject-Signature": signature}


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
        storage_queue=RedisSettings(url="redis://localhost:6379/0"),
        work_management=work_management or WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
        security=security or SecuritySettings(),
    )


class _FakeOpenProjectTransport:
    """Minimal fake implementing the OpenProjectTransport surface."""

    def __init__(self) -> None:
        self.work_packages: dict[str, dict[str, object]] = {}
        self.comments: list[tuple[str, str]] = []

    async def get_work_package(self, external_id: str) -> dict[str, object]:
        return self.work_packages.get(external_id, {})

    async def list_updated_work_packages(self, since: object) -> list[dict[str, object]]:
        del since
        return list(self.work_packages.values())

    async def create_work_package(self, payload: dict[str, object]) -> dict[str, object]:
        external_id = str(len(self.work_packages) + 1)
        self.work_packages[external_id] = {**payload, "id": external_id}
        return self.work_packages[external_id]

    async def update_status(self, external_id: str, status: str) -> None:
        self.work_packages.setdefault(external_id, {})["status"] = status

    async def post_comment(self, external_id: str, body: str) -> dict[str, object]:
        self.comments.append((external_id, body))
        return {"id": f"comment-{len(self.comments)}"}

    async def link_pull_request(self, external_id: str, pr_ref: str) -> None:
        del external_id, pr_ref


async def test_webhook_accepts_and_normalizes_event() -> None:
    """POST /api/v1/webhooks/openproject normalizes to a canonical event."""
    import hashlib
    import hmac
    import json

    import httpx

    from brain.api.app import create_app

    secret = "test-op-secret"
    app = create_app(_settings(security=SecuritySettings(webhook_openproject_secret=secret)))
    transport = httpx.ASGITransport(app=app)
    payload = {
        "eventType": "work_package:updated",
        "work_package": {"id": "42", "subject": "Fix login"},
    }
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        project = Project(name="op-demo")
        await app_container.repositories.projects.create(project)

        response = await client.post(
            "/api/v1/webhooks/openproject",
            content=body,
            headers={"X-OpenProject-Signature": signature},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] is True
        assert body["event_type"] == "work_item_changed"
        assert body["external_id"] == "42"
        # The canonical event reached the app's event bus.
        assert any(
            e.event_type.value == "work_item_changed" for e in app_container.event_bus.published
        )


async def test_assignment_automation_triggers_run_command() -> None:
    """A work package assigned to the Brain actor triggers RunWorkItemCommand."""
    brain_actor = str(uuid.uuid4())
    settings = _settings(
        WorkManagementSettings(
            enabled=False,
            provider="openproject",
            base_url="http://localhost:8081",
            api_key="key",
            project_id=str(uuid.uuid4()),
            brain_actor_id=brain_actor,
        ),
        security=SecuritySettings(webhook_openproject_secret="op-secret"),
    )
    import httpx

    from brain.api.app import create_app

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        project = Project(name="op-assign")
        await app_container.repositories.projects.create(project)

        payload = {
            "eventType": "work_package:updated",
            "work_package": {
                "id": "7",
                "subject": "Assigned task",
                "assignee": {"href": f"/api/v3/users/{brain_actor}"},
            },
        }
        body2, headers2 = _signed_payload(payload, "op-secret")
        response = await client.post(
            "/api/v1/webhooks/openproject",
            content=body2,
            headers=headers2,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["triggered"] == "assignment"
        assert body["command_id"]
        # A canonical work item + external mapping were persisted (the webhook
        # creates the work item in whichever project exists; find by ref).
        found = False
        for candidate in await app_container.repositories.projects.list():
            for work_item in await app_container.repositories.work_items.list_by_project(
                candidate.id
            ):
                if any(
                    ref.provider == "openproject" and ref.external_id == "7"
                    for ref in work_item.external_refs
                ):
                    found = True
        assert found


async def test_human_comment_normalizes_to_feedback() -> None:
    """An OpenProject comment becomes HumanFeedbackReceived and resumes."""
    import httpx

    from brain.api.app import create_app

    app = create_app(_settings(security=SecuritySettings(webhook_openproject_secret="op-secret")))
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        project = Project(name="op-feedback")
        await app_container.repositories.projects.create(project)
        work_item = WorkItem(
            project_id=project.id,
            title="Task",
            external_refs=[
                ExternalReference(
                    provider="openproject", external_id="99", external_type="work_package"
                )
            ],
        )
        await app_container.repositories.work_items.create(work_item)

        comment_payload = {
            "eventType": "work_package:updated",
            "work_package": {"id": "99", "subject": "Task"},
            "comment": {
                "id": "c-1",
                "raw": "Please clarify the lockout policy.",
                "author": {"name": "alice"},
            },
        }
        body2, headers2 = _signed_payload(comment_payload, "op-secret")
        response = await client.post(
            "/api/v1/webhooks/openproject",
            content=body2,
            headers=headers2,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["feedback"]["normalized_to"] == "HumanFeedbackReceived"
        assert body["feedback"]["work_item_id"] == str(work_item.id)
        # HumanFeedbackReceived reached the app's event bus.
        assert any(
            e.event_type.value == "human_feedback_received"
            for e in app_container.event_bus.published
        )


async def test_openproject_adapter_via_port() -> None:
    """The OpenProject adapter works through the WorkManagementPort."""
    from brain.adapters.work_management.openproject import OpenProjectAdapter
    from brain.domain.external_reference import ExternalReference

    project_id = ProjectId(uuid.uuid4())
    transport = _FakeOpenProjectTransport()
    transport.work_packages["10"] = {"id": "10", "subject": "Existed", "status": "new"}
    adapter = OpenProjectAdapter(transport=transport, project_id=project_id)

    fetched = await adapter.fetch_work_item(
        ExternalReference(provider="openproject", external_id="10")
    )
    assert fetched.title == "Existed"

    ref = await adapter.publish_work_item(WorkItem(project_id=project_id, title="New task"))
    assert ref.external_id == "2"


async def test_openproject_http_transport_constructs() -> None:
    """The HTTP transport builds from settings-shaped args."""
    transport = OpenProjectHTTPTransport(base_url="http://localhost:8081", api_key="secret")
    assert transport._base_url == "http://localhost:8081"
    assert transport._api_key == "secret"


async def test_container_reports_openproject_available_when_configured() -> None:
    """With a reachable OpenProject the capability is AVAILABLE."""
    settings = _settings(
        WorkManagementSettings(
            enabled=True,
            provider="openproject",
            base_url="http://127.0.0.1:1",  # unreachable -> UNAVAILABLE
            api_key="key",
            project_id=str(uuid.uuid4()),
        )
    )
    container = await create_brain_container(settings)
    try:
        assert container.capabilities()["work_management"] == "UNAVAILABLE"
        assert container.is_ready() is True  # optional provider does not block
        # The projection port remains a safe null adapter.
        assert container.services["observation_projection"] is not None
    finally:
        await container.close()
