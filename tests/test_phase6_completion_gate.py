"""Phase 6 golden tests and completion gate.

Given a repository containing a FastAPI service, a Docker Compose file with
PostgreSQL + Redis, an OpenAPI spec, and a Kubernetes deployment, the topology
pipeline produces a canonical component/resource topology WITHOUT any human
catalog metadata: the FastAPI service is a backend service, PostgreSQL and
Redis are resources, the OpenAPI spec becomes a REST interface, claims are
recorded with provenance, and everything persists through the catalog.
"""

from __future__ import annotations

import uuid

from brain.adapters.in_memory.repositories import InMemorySoftwareCatalogRepository
from brain.adapters.topology.catalog import DerivedSoftwareCatalog
from brain.adapters.topology.discovery import TopologyDiscoverer
from brain.application.topology import TopologyDiscoveryService
from brain.domain.identity import new_project_id, new_repository_id
from brain.domain.projects import Project
from brain.domain.software_model import ComponentType, InterfaceType, ResourceType

REPOSITORY_ID = new_repository_id()
PROJECT_ID = new_project_id()

SNAPSHOT_FILES: dict[str, str] = {
    "pyproject.toml": (
        '[project]\nname = "api"\ndependencies = ["fastapi>=0.1", "uvicorn", "psycopg[binary]"]\n'
    ),
    "docker-compose.yml": """
services:
  api:
    image: acme/api:latest
    depends_on:
      - postgres
      - redis
  postgres:
    image: postgres:16
  redis:
    image: redis:7
""".strip(),
    "api/openapi.yaml": """
openapi: 3.0.0
info:
  title: Users API
paths:
  /users:
    get:
      responses: {}
""".strip(),
    "deploy/k8s/deployment.yaml": """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: acme/api:latest
""".strip(),
}


def _catalog_and_service() -> tuple[InMemorySoftwareCatalogRepository, TopologyDiscoveryService]:
    catalog = InMemorySoftwareCatalogRepository()
    service = TopologyDiscoveryService(discoverer=TopologyDiscoverer(), catalog=catalog)
    return catalog, service


async def test_gate_discovers_backend_component() -> None:
    catalog, service = _catalog_and_service()
    await service.discover_and_persist(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        revision="abc123",
        snapshot_files=SNAPSHOT_FILES,
    )
    components = await catalog.list_components(PROJECT_ID)
    names = {c.name for c in components}
    assert "api" in names
    api = next(c for c in components if c.name == "api")
    assert api.component_type == ComponentType.BACKEND_SERVICE
    assert REPOSITORY_ID in api.repository_ids


async def test_gate_discovers_postgres_and_redis_resources() -> None:
    catalog, service = _catalog_and_service()
    await service.discover_and_persist(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        revision="abc123",
        snapshot_files=SNAPSHOT_FILES,
    )
    resources = await catalog.list_resources(PROJECT_ID)
    by_name = {r.name: r.resource_type for r in resources}
    assert by_name.get("PostgreSQL") == ResourceType.POSTGRESQL
    assert by_name.get("Redis") == ResourceType.REDIS


async def test_gate_discovers_rest_interface() -> None:
    catalog, service = _catalog_and_service()
    await service.discover_and_persist(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        revision="abc123",
        snapshot_files=SNAPSHOT_FILES,
    )
    interfaces = await catalog.list_interfaces(PROJECT_ID)
    assert any(i.type == InterfaceType.REST for i in interfaces)
    assert any(i.name == "Users API" for i in interfaces)


async def test_gate_records_claims_with_provenance() -> None:
    catalog, service = _catalog_and_service()
    await service.discover_and_persist(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        revision="abc123",
        snapshot_files=SNAPSHOT_FILES,
    )
    claims = await catalog.list_claims(REPOSITORY_ID)
    assert len(claims) >= 1
    assert all(c.repository_id == REPOSITORY_ID for c in claims)
    assert all(c.revision == "abc123" for c in claims)


async def test_gate_records_compose_dependency() -> None:
    catalog, service = _catalog_and_service()
    await service.discover_and_persist(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        revision="abc123",
        snapshot_files=SNAPSHOT_FILES,
    )
    targets = await catalog.list_dependencies(PROJECT_ID, "api")
    assert "PostgreSQL" in targets
    assert "Redis" in targets


async def test_gate_creates_system() -> None:
    catalog, service = _catalog_and_service()
    await service.discover_and_persist(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        revision="abc123",
        snapshot_files=SNAPSHOT_FILES,
    )
    systems = await catalog.list_systems(PROJECT_ID)
    assert len(systems) == 1
    assert systems[0].project_id == PROJECT_ID
    assert len(systems[0].component_ids) >= 1


async def test_gate_derived_catalog_reads_topology_without_external_metadata() -> None:
    catalog, service = _catalog_and_service()
    await service.discover_and_persist(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        revision="abc123",
        snapshot_files=SNAPSHOT_FILES,
    )
    project = Project(id=PROJECT_ID, name="demo")
    derived = DerivedSoftwareCatalog(catalog)

    components = await derived.list_components(project)
    assert any(c.name == "api" for c in components)

    resources = await derived.list_resources(project)
    assert any(r.name == "PostgreSQL" for r in resources)
    assert any(r.name == "Redis" for r in resources)

    interfaces = await derived.list_interfaces(project)
    assert any(i.name == "Users API" for i in interfaces)

    deps = await derived.get_dependencies(project, "api")
    assert "PostgreSQL" in deps
    assert "Redis" in deps


async def test_gate_same_repository_produces_stable_topology() -> None:
    first_catalog, service = _catalog_and_service()
    await service.discover_and_persist(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        revision="abc123",
        snapshot_files=SNAPSHOT_FILES,
    )
    second_catalog, service2 = _catalog_and_service()
    await service2.discover_and_persist(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        revision="abc123",
        snapshot_files=SNAPSHOT_FILES,
    )
    first = {c.name for c in await first_catalog.list_components(PROJECT_ID)}
    second = {c.name for c in await second_catalog.list_components(PROJECT_ID)}
    assert first == second
    assert "api" in first


async def test_gate_ignores_repository_without_topology_signals() -> None:
    catalog, service = _catalog_and_service()
    await service.discover_and_persist(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        revision="abc123",
        snapshot_files={"README.md": "# just docs\n"},
    )
    assert await catalog.list_components(PROJECT_ID) == []
    assert await catalog.list_resources(PROJECT_ID) == []


def test_gate_has_real_repository_ids() -> None:
    assert uuid.UUID(int=0) != REPOSITORY_ID
    assert uuid.UUID(int=0) != PROJECT_ID
