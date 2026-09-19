"""Phase 3 gate tests: pull-reconciliation runtime wiring.

The scheduler enqueues (or runs inline) work-management pulls for projects
with a provider reference when ``sync_enabled``; ``POST
/api/v1/work-management/sync`` enqueues the same command (BOTH trigger).
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from brain.api.app import create_app
from brain.bootstrap.container import create_brain_container
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
from brain.domain.external_reference import ExternalReference
from brain.domain.projects import Project
from brain.scheduler.reconciliation import ReconciliationService
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
        work_management=WorkManagementSettings(enabled=True, sync_enabled=True),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
    )


class _FakePullService:
    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    async def sync_project(self, project: object) -> object:
        self.calls.append(project.id)  # type: ignore[attr-defined]
        return {
            "project_id": project.id,  # type: ignore[attr-defined]
            "status": "ok",
            "items_pulled": 0,
        }


class _FakeWorkManagement:
    pass


async def _seed_provider_project(container: object) -> Project:
    project = Project(
        name="provider-project",
        external_refs=[
            ExternalReference(provider="openproject", external_id="8", external_type="project")
        ],
    )
    await container.repositories.projects.create(project)  # type: ignore[attr-defined]
    return project


async def test_gate_scheduler_runs_pull_inline_without_queue() -> None:
    container = await create_brain_container(_settings())
    try:
        project = await _seed_provider_project(container)
        fake = _FakePullService()
        container.services["openproject_pull_sync"] = fake  # type: ignore[attr-defined]
        container.work_management = _FakeWorkManagement()  # type: ignore[attr-defined]

        from brain.scheduler.reconciliation import ReconciliationReport

        service = ReconciliationService(container)
        report = ReconciliationReport()
        await service.reconcile_work_management(report)
        assert report.work_management_checked >= 1
        assert report.work_management_synced >= 1
        assert fake.calls == [project.id]
    finally:
        await container.close()


async def test_gate_scheduler_enqueues_pull_with_queue() -> None:
    container = await create_brain_container(_settings())
    try:
        await _seed_provider_project(container)
        container.services["openproject_pull_sync"] = _FakePullService()  # type: ignore[attr-defined]
        container.work_management = _FakeWorkManagement()  # type: ignore[attr-defined]

        from brain.adapters.in_memory.commands import InMemoryCommandQueue

        queue = InMemoryCommandQueue()
        service = ReconciliationService(container, queue=queue)  # type: ignore[arg-type]
        from brain.scheduler.reconciliation import ReconciliationReport

        report = ReconciliationReport()
        await service.reconcile_work_management(report)
        assert report.work_management_synced >= 1
        assert await queue.pending_count() >= 1
    finally:
        await container.close()


async def test_gate_scheduler_skips_when_sync_disabled() -> None:
    settings = _settings()
    settings.work_management.sync_enabled = False
    container = await create_brain_container(settings)
    try:
        await _seed_provider_project(container)
        container.services["openproject_pull_sync"] = _FakePullService()  # type: ignore[attr-defined]
        container.work_management = _FakeWorkManagement()  # type: ignore[attr-defined]

        from brain.scheduler.reconciliation import ReconciliationReport

        service = ReconciliationService(container)
        report = ReconciliationReport()
        await service.reconcile_work_management(report)
        assert report.work_management_checked == 0
        assert report.work_management_synced == 0
    finally:
        await container.close()


async def test_gate_api_sync_endpoint_returns_202() -> None:
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        app_container = app.state.container
        project = await _seed_provider_project(app_container)

        response = await client.post(
            "/api/v1/work-management/sync",
            json={"project_id": str(project.id)},
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "ACCEPTED"
        assert body["command_id"]

        from brain.ports.commands import CommandQueue

        queue = app_container.services["command_queue"]
        assert isinstance(queue, CommandQueue)
        assert await queue.pending_count() >= 1


async def test_gate_api_sync_endpoint_validates() -> None:
    app = create_app(_settings())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        missing = await client.post("/api/v1/work-management/sync", json={})
        assert missing.status_code == 422
        unknown = await client.post(
            "/api/v1/work-management/sync",
            json={"project_id": str(uuid.uuid4())},
        )
        assert unknown.status_code == 404
