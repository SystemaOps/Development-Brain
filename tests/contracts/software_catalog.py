"""SoftwareCatalogRepository contract."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.knowledge import (
    DiscoveryMethod,
    KnowledgeConfidence,
    KnowledgeEvidence,
    KnowledgeOrigin,
)
from brain.domain.projects import Project
from brain.domain.software_model import (
    ComponentType,
    Interface,
    InterfaceType,
    Resource,
    ResourceType,
    SoftwareComponent,
    SoftwareDomain,
    System,
)
from brain.domain.topology import CandidateKind, DependencyCandidate, TopologyClaim
from brain.ports.topology import SoftwareCatalogRepository


def _evidence() -> KnowledgeEvidence:
    return KnowledgeEvidence(
        source_type="test",
        source_id="contract",
        discovery_method=DiscoveryMethod.MANIFEST_ANALYSIS,
        origin=KnowledgeOrigin.DISCOVERED,
        confidence=KnowledgeConfidence.HIGH,
    )


def _component(project_id: ProjectId, name: str) -> SoftwareComponent:
    return SoftwareComponent(
        project_id=project_id,
        name=name,
        component_type=ComponentType.BACKEND_SERVICE,
        provenance=[_evidence()],
    )


class SoftwareCatalogRepositoryContract:
    @pytest.fixture
    def catalog_repository(self) -> SoftwareCatalogRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, catalog_repository: SoftwareCatalogRepository) -> None:
        assert isinstance(catalog_repository, SoftwareCatalogRepository)

    async def test_upsert_component_round_trip(
        self, catalog_repository: SoftwareCatalogRepository
    ) -> None:
        project = Project(name="auth")
        component = _component(project.id, "api")
        stored = await catalog_repository.upsert_component(component)
        assert stored.id == component.id
        assert component.id in [c.id for c in await catalog_repository.list_components(project.id)]

    async def test_upsert_component_is_idempotent(
        self, catalog_repository: SoftwareCatalogRepository
    ) -> None:
        project = Project(name="auth")
        component = _component(project.id, "api")
        await catalog_repository.upsert_component(component)
        await catalog_repository.upsert_component(component)
        components = await catalog_repository.list_components(project.id)
        assert [c.id for c in components] == [component.id]

    async def test_list_components_scoped_to_project(
        self, catalog_repository: SoftwareCatalogRepository
    ) -> None:
        project_a = Project(name="a")
        project_b = Project(name="b")
        await catalog_repository.upsert_component(_component(project_a.id, "api"))
        await catalog_repository.upsert_component(_component(project_b.id, "web"))
        assert len(await catalog_repository.list_components(project_a.id)) == 1
        assert len(await catalog_repository.list_components(project_b.id)) == 1

    async def test_upsert_interface_round_trip(
        self, catalog_repository: SoftwareCatalogRepository
    ) -> None:
        project = Project(name="auth")
        component = _component(project.id, "api")
        await catalog_repository.upsert_component(component)
        interface = Interface(component_id=component.id, type=InterfaceType.REST, name="user-api")
        await catalog_repository.upsert_interface(interface)
        interfaces = await catalog_repository.list_interfaces(project.id)
        assert [i.id for i in interfaces] == [interface.id]

    async def test_upsert_resource_round_trip(
        self, catalog_repository: SoftwareCatalogRepository
    ) -> None:
        project = Project(name="auth")
        resource = Resource(
            project_id=project.id, name="PostgreSQL", resource_type=ResourceType.POSTGRESQL
        )
        await catalog_repository.upsert_resource(resource)
        resources = await catalog_repository.list_resources(project.id)
        assert [r.id for r in resources] == [resource.id]

    async def test_upsert_system_round_trip(
        self, catalog_repository: SoftwareCatalogRepository
    ) -> None:
        project = Project(name="auth")
        system = System(project_id=project.id, name="default", component_ids=[uuid.uuid4()])
        await catalog_repository.upsert_system(system)
        systems = await catalog_repository.list_systems(project.id)
        assert [s.id for s in systems] == [system.id]

    async def test_upsert_domain_round_trip(
        self, catalog_repository: SoftwareCatalogRepository
    ) -> None:
        project = Project(name="auth")
        domain = SoftwareDomain(project_id=project.id, name="core")
        stored = await catalog_repository.upsert_domain(domain)
        assert stored.id == domain.id

    async def test_save_and_list_claims(
        self, catalog_repository: SoftwareCatalogRepository
    ) -> None:
        repository_id = RepositoryId(uuid.uuid4())
        claim = TopologyClaim(
            entity_kind=CandidateKind.COMPONENT,
            entity_name="api",
            value="backend_service",
            repository_id=repository_id,
            revision="abc123",
            provenance=_evidence(),
        )
        await catalog_repository.save_claims([claim])
        claims = await catalog_repository.list_claims(repository_id)
        assert [c.id for c in claims] == [claim.id]

    async def test_save_and_list_dependencies(
        self, catalog_repository: SoftwareCatalogRepository
    ) -> None:
        project = Project(name="auth")
        repository_id = RepositoryId(uuid.uuid4())
        dependency = DependencyCandidate(
            source="api",
            target="PostgreSQL",
            project_id=project.id,
            repository_id=repository_id,
            revision="abc123",
            provenance=_evidence(),
        )
        await catalog_repository.save_dependencies([dependency])
        targets = await catalog_repository.list_dependencies(project.id, "api")
        assert targets == ["PostgreSQL"]

    async def test_empty_lists(self, catalog_repository: SoftwareCatalogRepository) -> None:
        project = Project(name="auth")
        assert await catalog_repository.list_components(project.id) == []
        assert await catalog_repository.list_interfaces(project.id) == []
        assert await catalog_repository.list_resources(project.id) == []
        assert await catalog_repository.list_systems(project.id) == []
        assert await catalog_repository.list_dependencies(project.id, "none") == []
