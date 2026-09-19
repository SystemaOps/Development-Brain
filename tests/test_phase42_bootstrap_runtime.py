"""Phase 2 gate tests: bootstrap runtime entry points.

POST /api/v1/projects/{id}/bootstrap returns 202 and enqueues a
BOOTSTRAP_PROJECT command.  The endpoint works without a live OpenProject
instance (bootstrap executes asynchronously in the worker).
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from brain.api.app import create_app
from brain.bootstrap.settings import (
    BrainSettings,
    DocumentationSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
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


def _settings() -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
        storage_semantic=WeaviateSettings(host="localhost"),
        storage_queue=RedisSettings(url="redis://localhost:6379/0", provider="inmemory"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
    )


async def _post_bootstrap(
    client: httpx.AsyncClient, project_id: uuid.UUID, payload: dict[str, object]
) -> httpx.Response:
    return await client.post(
        f"/api/v1/projects/{project_id}/bootstrap",
        json=payload,
    )


async def test_bootstrap_endpoint_returns_202_and_enqueues() -> None:
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        project = Project(name="bootstrap-target")
        await app_container.repositories.projects.create(project)

        response = await _post_bootstrap(client, project.id, {"external_project_id": "8"})
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "ACCEPTED"
        assert body["command_id"]

        from brain.ports.commands import CommandQueue

        queue = app_container.services["command_queue"]
        assert isinstance(queue, CommandQueue)
        assert await queue.pending_count() >= 1


async def test_bootstrap_endpoint_validates_external_id() -> None:
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        response = await _post_bootstrap(client, uuid.uuid4(), {})
        assert response.status_code == 422


async def test_bootstrap_endpoint_requires_existing_project() -> None:
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        response = await _post_bootstrap(client, uuid.uuid4(), {"external_project_id": "8"})
        assert response.status_code == 404
