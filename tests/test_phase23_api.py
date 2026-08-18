"""Phase 23 golden tests and completion gate.

The Brain starts as a FastAPI service, exposes canonical APIs, and does not
depend on optional human integrations for startup.  Tests cover schema
generation, validation, 404 behavior, error envelope, correlation IDs, and
core CRUD/query paths (Task 23.21).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

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
        storage_queue=RedisSettings(url="redis://localhost:6379/0"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(_settings())) as test_client:
        yield test_client


def test_openapi_schema_generates(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Software Development Brain API"
    assert "/health/live" in schema["paths"]
    assert "/api/v1/projects" in schema["paths"]
    assert "/api/v1/work-items" in schema["paths"]
    assert "/api/v1/contexts/build" in schema["paths"]


def test_health_live(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_ready(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_capabilities_route(client: TestClient) -> None:
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["postgres"]["status"] == "AVAILABLE"
    assert body["work_management"]["status"] == "DISABLED"
    assert body["documentation_xwiki"]["status"] == "DISABLED"


def test_system_status_and_version(client: TestClient) -> None:
    status = client.get("/api/v1/system/status").json()
    assert status["ready"] is True
    assert "executors" in status
    version = client.get("/api/v1/system/version").json()
    assert version["version"] == "0.1.0"


def test_correlation_header_generated(client: TestClient) -> None:
    response = client.get("/health/live")
    assert "X-Correlation-ID" in response.headers
    assert uuid.UUID(response.headers["X-Correlation-ID"])


def test_correlation_header_preserves_incoming(client: TestClient) -> None:
    correlation_id = str(uuid.uuid4())
    response = client.get("/health/live", headers={"X-Correlation-ID": correlation_id})
    assert response.headers["X-Correlation-ID"] == correlation_id


def test_error_envelope_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert "message" in body
    assert "correlation_id" in body


def test_error_envelope_validation(client: TestClient) -> None:
    response = client.post("/api/v1/projects", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert "details" in body


def test_project_crud_flow(client: TestClient) -> None:
    created = client.post("/api/v1/projects", json={"name": "demo"})
    assert created.status_code == 201
    project_id = created.json()["id"]

    fetched = client.get(f"/api/v1/projects/{project_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "demo"

    listed = client.get("/api/v1/projects")
    assert any(p["id"] == project_id for p in listed.json())

    updated = client.patch(f"/api/v1/projects/{project_id}", json={"description": "updated"})
    assert updated.status_code == 200
    assert updated.json()["description"] == "updated"


def test_repository_registration_flow(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "repo-demo"}).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/repositories",
        json={"name": "app", "clone_url": "git@example:app.git"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "app"
    assert body["project_id"] == project["id"]


def test_work_item_crud_flow(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "work-demo"}).json()
    created = client.post(
        "/api/v1/work-items",
        json={"project_id": project["id"], "title": "Fix login"},
    )
    assert created.status_code == 201
    work_item_id = created.json()["id"]

    fetched = client.get(f"/api/v1/work-items/{work_item_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Fix login"

    updated = client.patch(
        f"/api/v1/work-items/{work_item_id}", json={"description": "reset counter"}
    )
    assert updated.status_code == 200

    run = client.post(f"/api/v1/work-items/{work_item_id}/run")
    assert run.status_code == 202
    assert run.json()["status"] == "ACCEPTED"


def test_requirement_crud_flow(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "req-demo"}).json()
    created = client.post(
        "/api/v1/requirements",
        json={"project_id": project["id"], "title": "Account lockout"},
    )
    assert created.status_code == 201
    requirement_id = created.json()["id"]

    fetched = client.get(f"/api/v1/requirements/{requirement_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Account lockout"


def test_async_endpoints_return_202(client: TestClient) -> None:
    for path in ("/api/v1/system/reconcile",):
        response = client.post(path)
        assert response.status_code == 202
        assert response.json()["status"] == "ACCEPTED"


def test_unknown_route_returns_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert "code" in body
    assert "message" in body
