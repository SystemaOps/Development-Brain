"""Unit tests for the Phase 6 topology discovery adapters."""

from __future__ import annotations

import pytest

from brain.adapters.topology.api import ApiInterfaceDetector
from brain.adapters.topology.deployment import DeploymentTopologyDetector
from brain.adapters.topology.manifest import ManifestTopologyDetector
from brain.adapters.topology.resources import ResourceDetector
from brain.domain.identity import RepositoryId
from brain.domain.software_model import ComponentType, InterfaceType
from brain.domain.topology import DiscoveredTopology


def _repository_id() -> RepositoryId:
    import uuid

    return RepositoryId(uuid.uuid4())


async def test_manifest_detects_python_backend() -> None:
    files = {
        "pyproject.toml": (
            '[project]\nname = "auth-service"\n'
            'dependencies = ["fastapi>=0.1", "uvicorn", "psycopg[binary]"]\n'
        )
    }
    topology = ManifestTopologyDetector().detect(_repository_id(), "abc", files)
    names = [c.name for c in topology.components]
    assert "auth-service" in names
    assert topology.components[0].component_type == ComponentType.BACKEND_SERVICE
    assert any(r.name == "PostgreSQL" for r in topology.resources)


async def test_manifest_detects_frontend_from_package_json() -> None:
    files = {"package.json": '{"name": "web-app", "dependencies": {"react": "^18.0.0"}}'}
    topology = ManifestTopologyDetector().detect(_repository_id(), "abc", files)
    assert topology.components[0].name == "web-app"
    assert topology.components[0].component_type == ComponentType.FRONTEND_APPLICATION


async def test_manifest_skips_requirements_when_pyproject_present() -> None:
    files = {
        "pyproject.toml": '[project]\nname = "auth-service"\n',
        "requirements.txt": "flask==3.0.0\n",
    }
    topology = ManifestTopologyDetector().detect(_repository_id(), "abc", files)
    names = [c.name for c in topology.components]
    assert names == ["auth-service"]


async def test_deployment_detects_compose_services() -> None:
    files = {
        "docker-compose.yml": """
version: "3"
services:
  api:
    image: myapp/api:latest
  postgres:
    image: postgres:16
    ports: ["5432:5432"]
  redis:
    image: redis:7
""".strip()
    }
    topology = DeploymentTopologyDetector().detect(_repository_id(), "abc", files)
    names = [c.name for c in topology.components]
    assert "api" in names
    assert topology.components[0].component_type == ComponentType.BACKEND_SERVICE
    resource_names = [r.name for r in topology.resources]
    assert "PostgreSQL" in resource_names
    assert "Redis" in resource_names


async def test_deployment_detects_k8s_manifest() -> None:
    files = {
        "deploy/k8s/deployment.yaml": """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker
  labels:
    app: worker
spec:
  template:
    metadata:
      labels:
        app: worker
""".strip()
    }
    topology = DeploymentTopologyDetector().detect(_repository_id(), "abc", files)
    assert any(c.name == "worker" for c in topology.components)


async def test_deployment_detects_terraform_resource() -> None:
    files = {
        "infra/main.tf": """
resource "aws_db_instance" "main" {
  engine = "postgres"
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "artifacts"
}
""".strip()
    }
    topology = DeploymentTopologyDetector().detect(_repository_id(), "abc", files)
    resource_names = [r.name for r in topology.resources]
    assert "PostgreSQL" in resource_names
    assert "S3/MinIO" in resource_names


async def test_api_detects_openapi_spec() -> None:
    files = {
        "api/openapi.yaml": """
openapi: 3.0.0
info:
  title: User API
paths:
  /users:
    get:
      responses: {}
""".strip()
    }
    topology = ApiInterfaceDetector().detect(_repository_id(), "abc", files, ["api"])
    assert any(i.name == "User API" for i in topology.interfaces)
    assert topology.interfaces[0].interface_type == InterfaceType.REST


async def test_api_detects_graphql_schema() -> None:
    files = {"api/schema.graphql": "type Query { user: User }"}
    topology = ApiInterfaceDetector().detect(_repository_id(), "abc", files, ["api"])
    assert topology.interfaces[0].interface_type == InterfaceType.GRAPHQL


async def test_resource_detector_finds_url_and_env() -> None:
    files = {
        ".env": "DATABASE_URL=postgresql://localhost/app\n",
        "config/application.yml": "redis:\n  host: localhost\n",
    }
    topology = ResourceDetector().detect(_repository_id(), "abc", files)
    names = {r.name for r in topology.resources}
    assert "PostgreSQL" in names
    assert "Redis" in names


async def test_resource_detector_ignores_manifests() -> None:
    files = {
        "pyproject.toml": "redis>=5\npostgresql>=1\n",
        "requirements.txt": "redis==5.0\n",
    }
    topology = ResourceDetector().detect(_repository_id(), "abc", files)
    assert topology.resources == []


async def test_merge_is_idempotent() -> None:
    repo_id = _repository_id()
    first = DiscoveredTopology(repository_id=repo_id, revision="abc")
    second = DiscoveredTopology(repository_id=repo_id, revision="abc")
    topology = first
    topology.merge(second)
    assert len(topology.components) == 0
    assert len(topology.interfaces) == 0
    assert len(topology.resources) == 0


@pytest.mark.parametrize("path", ["", ".env.example", "config.yml"])
async def test_resource_detector_tolerates_empty_inputs(path: str) -> None:
    files = {path: ""}
    topology = ResourceDetector().detect(_repository_id(), "abc", files)
    assert isinstance(topology, DiscoveredTopology)
