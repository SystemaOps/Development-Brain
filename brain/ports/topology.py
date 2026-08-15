"""Software topology discovery and derived catalog ports (Phase 6).

``TopologyDiscoveryPort`` is the pluggable discovery interface: adapters that
read repository snapshots (manifests, deployment files, API schemas) and emit
candidates.  ``SoftwareCatalogRepository`` persists the reconciled canonical
entities so the derived catalog works without an external catalog.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.projects import Project
from brain.domain.software_model import (
    Interface,
    Resource,
    SoftwareComponent,
    SoftwareDomain,
    System,
)
from brain.domain.topology import (
    DependencyCandidate,
    DiscoveredTopology,
    TopologyClaim,
)


@runtime_checkable
class TopologyDiscoveryPort(Protocol):
    """Discovers topology candidates from a repository snapshot."""

    async def discover(
        self, repository_id: RepositoryId, revision: str, snapshot_files: dict[str, str]
    ) -> DiscoveredTopology: ...


@runtime_checkable
class SoftwareCatalogRepository(Protocol):
    """Persists and queries the canonical (reconciled) software catalog.

    This is the brain-owned state layer for discovered + declared topology;
    an external catalog (Backstage, ...) is only ever a second source of claims.
    """

    async def upsert_domain(self, domain: SoftwareDomain) -> SoftwareDomain: ...

    async def upsert_system(self, system: System) -> System: ...

    async def upsert_component(self, component: SoftwareComponent) -> SoftwareComponent: ...

    async def upsert_interface(self, interface: Interface) -> Interface: ...

    async def upsert_resource(self, resource: Resource) -> Resource: ...

    async def save_claims(self, claims: list[TopologyClaim]) -> list[TopologyClaim]: ...

    async def save_dependencies(
        self, dependencies: list[DependencyCandidate]
    ) -> list[DependencyCandidate]: ...

    async def list_claims(self, repository_id: RepositoryId) -> list[TopologyClaim]: ...

    async def list_systems(self, project_id: ProjectId) -> list[System]: ...

    async def list_components(self, project_id: ProjectId) -> list[SoftwareComponent]: ...

    async def list_interfaces(self, project_id: ProjectId) -> list[Interface]: ...

    async def list_resources(self, project_id: ProjectId) -> list[Resource]: ...

    async def list_dependencies(self, project_id: ProjectId, component_name: str) -> list[str]: ...


@runtime_checkable
class DerivedSoftwareCatalog(Protocol):
    """Catalog read API that works without an external catalog.

    Combines the persisted canonical entities with reconciliation claims so
    callers get a consistent view whether or not Backstage is configured.
    """

    async def list_components(self, project: Project) -> list[SoftwareComponent]: ...

    async def list_interfaces(self, project: Project) -> list[Interface]: ...

    async def list_resources(self, project: Project) -> list[Resource]: ...

    async def list_systems(self, project: Project) -> list[System]: ...

    async def get_dependencies(self, project: Project, component_name: str) -> list[str]: ...


__all__ = [
    "DerivedSoftwareCatalog",
    "SoftwareCatalogRepository",
    "TopologyDiscoveryPort",
]
