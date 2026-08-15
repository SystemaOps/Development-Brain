"""Unit tests for the Phase 6 reconciler, discovery service, and derived catalog."""

from __future__ import annotations

import uuid

import pytest

from brain.adapters.in_memory.repositories import InMemorySoftwareCatalogRepository
from brain.adapters.topology.catalog import DerivedSoftwareCatalog
from brain.adapters.topology.discovery import TopologyDiscoverer
from brain.application.topology import TopologyDiscoveryService
from brain.domain.identity import RepositoryId
from brain.domain.knowledge import (
    KnowledgeConfidence,
    KnowledgeEvidence,
    KnowledgeOrigin,
)
from brain.domain.projects import Project
from brain.domain.software_model import ComponentType
from brain.domain.topology import (
    CandidateKind,
    ComponentCandidate,
    DiscoveredTopology,
    TopologyClaim,
    TopologyReconciler,
)


def _evidence(origin: KnowledgeOrigin = KnowledgeOrigin.DISCOVERED) -> KnowledgeEvidence:
    return KnowledgeEvidence(
        source_type="test",
        source_id="unit",
        origin=origin,
        confidence=KnowledgeConfidence.HIGH,
    )


def test_reconciler_builds_claims_from_topology() -> None:
    repository_id = RepositoryId(uuid.uuid4())
    topology = DiscoveredTopology(
        repository_id=repository_id,
        revision="abc",
        components=[
            ComponentCandidate(
                name="api",
                component_type=ComponentType.BACKEND_SERVICE,
                repository_id=repository_id,
                revision="abc",
                provenance=_evidence(),
            )
        ],
    )
    claims = TopologyReconciler().claims(topology)
    assert len(claims) == 1
    assert claims[0].entity_kind == CandidateKind.COMPONENT
    assert claims[0].entity_name == "api"
    assert claims[0].value == "backend_service"
    assert claims[0].origin == "discovered"


def test_reconciler_declared_wins_over_discovered() -> None:
    repository_id = RepositoryId(uuid.uuid4())
    declared = TopologyClaim(
        entity_kind=CandidateKind.COMPONENT,
        entity_name="api",
        value="library",
        repository_id=repository_id,
        revision="abc",
        origin="declared",
        provenance=_evidence(KnowledgeOrigin.DECLARED),
    )
    discovered = TopologyClaim(
        entity_kind=CandidateKind.COMPONENT,
        entity_name="api",
        value="backend_service",
        repository_id=repository_id,
        revision="abc",
        provenance=_evidence(KnowledgeOrigin.DISCOVERED),
    )
    winners = TopologyReconciler().reconcile([discovered, declared])
    assert winners[(CandidateKind.COMPONENT, "api")] == "library"


def test_reconciler_keeps_all_claims() -> None:
    repository_id = RepositoryId(uuid.uuid4())
    claims = [
        TopologyClaim(
            entity_kind=CandidateKind.COMPONENT,
            entity_name="api",
            value="library",
            repository_id=repository_id,
            revision="abc",
            origin="declared",
            provenance=_evidence(KnowledgeOrigin.DECLARED),
        ),
        TopologyClaim(
            entity_kind=CandidateKind.COMPONENT,
            entity_name="api",
            value="backend_service",
            repository_id=repository_id,
            revision="abc",
            provenance=_evidence(KnowledgeOrigin.DISCOVERED),
        ),
    ]
    reconciler = TopologyReconciler()
    reconciler.reconcile(claims)
    assert len(claims) == 2


async def test_discovery_service_persists_entities() -> None:
    repository_id = RepositoryId(uuid.uuid4())
    project = Project(name="auth")
    catalog = InMemorySoftwareCatalogRepository()
    service = TopologyDiscoveryService(discoverer=TopologyDiscoverer(), catalog=catalog)

    files = {
        "pyproject.toml": '[project]\nname = "auth-service"\ndependencies = ["fastapi"]\n',
        "docker-compose.yml": """
services:
  auth:
    image: auth:latest
  postgres:
    image: postgres:16
""".strip(),
    }

    result = await service.discover_and_persist(
        project_id=project.id,
        repository_id=repository_id,
        revision="abc",
        snapshot_files=files,
    )

    components = await catalog.list_components(project.id)
    names = {c.name for c in components}
    assert "auth-service" in names
    assert "auth" in names
    assert all(c.project_id == project.id for c in components)

    resources = await catalog.list_resources(project.id)
    assert any(r.name == "PostgreSQL" for r in resources)

    systems = await catalog.list_systems(project.id)
    assert len(systems) == 1
    assert systems[0].project_id == project.id

    claims = await catalog.list_claims(repository_id)
    assert len(claims) >= 1

    assert result.topology.repository_id == repository_id


async def test_derived_catalog_lists_components() -> None:
    project = Project(name="auth")
    catalog = InMemorySoftwareCatalogRepository()
    derived = DerivedSoftwareCatalog(catalog)

    assert await derived.list_components(project) == []

    repository_id = RepositoryId(uuid.uuid4())
    files = {"pyproject.toml": '[project]\nname = "auth-service"\n'}
    service = TopologyDiscoveryService(discoverer=TopologyDiscoverer(), catalog=catalog)
    await service.discover_and_persist(
        project_id=project.id,
        repository_id=repository_id,
        revision="abc",
        snapshot_files=files,
    )

    components = await derived.list_components(project)
    assert [c.name for c in components] == ["auth-service"]


@pytest.mark.parametrize("empty", [{}, {"README.md": "no topology here"}])
async def test_discovery_service_tolerates_empty_repositories(empty: dict[str, str]) -> None:
    repository_id = RepositoryId(uuid.uuid4())
    project = Project(name="auth")
    catalog = InMemorySoftwareCatalogRepository()
    service = TopologyDiscoveryService(discoverer=TopologyDiscoverer(), catalog=catalog)

    result = await service.discover_and_persist(
        project_id=project.id,
        repository_id=repository_id,
        revision="abc",
        snapshot_files=empty,
    )
    assert result.components == []
    assert result.resources == []
