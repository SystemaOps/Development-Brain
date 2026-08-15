"""Software topology discovery application service (Phase 6).

Orchestrates the pipeline:

1. run the :class:`TopologyDiscoveryPort` over a repository's file contents
   (from a snapshot / revision);
2. reconcile the discovered candidates into claims (Task 6.7);
3. persist the reconciled canonical entities (components, interfaces,
   resources, systems, dependencies) through :class:`SoftwareCatalogRepository`.

The service depends only on ports, so it runs against the in-memory reference
adapters and PostgreSQL alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.software_model import (
    Interface,
    InterfaceType,
    Resource,
    SoftwareComponent,
    System,
)
from brain.domain.topology import (
    DiscoveredTopology,
    TopologyClaim,
    TopologyReconciler,
)
from brain.ports.topology import SoftwareCatalogRepository, TopologyDiscoveryPort


@dataclass
class TopologyDiscoveryResult:
    topology: DiscoveredTopology
    claims: list[TopologyClaim] = field(default_factory=list)
    systems: list[System] = field(default_factory=list)
    components: list[SoftwareComponent] = field(default_factory=list)
    interfaces: list[Interface] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)


class TopologyDiscoveryService:
    def __init__(
        self,
        *,
        discoverer: TopologyDiscoveryPort,
        catalog: SoftwareCatalogRepository,
        reconciler: TopologyReconciler | None = None,
    ) -> None:
        self._discoverer = discoverer
        self._catalog = catalog
        self._reconciler = reconciler or TopologyReconciler()

    async def discover_and_persist(
        self,
        *,
        project_id: ProjectId,
        repository_id: RepositoryId,
        revision: str,
        snapshot_files: dict[str, str],
    ) -> TopologyDiscoveryResult:
        topology = await self._discoverer.discover(repository_id, revision, snapshot_files)

        claims = self._reconciler.claims(topology)
        await self._catalog.save_claims(claims)

        dependencies = topology.dependencies
        for dependency in dependencies:
            dependency.project_id = project_id
        await self._catalog.save_dependencies(dependencies)

        components = [
            SoftwareComponent(
                project_id=project_id,
                name=c.name,
                component_type=c.component_type,
                repository_ids=[c.repository_id],
                provenance=[c.provenance],
            )
            for c in topology.components
        ]
        systems = self._systems(project_id, components)
        interfaces = self._interfaces(project_id, components, topology)
        resources = [
            Resource(
                project_id=project_id,
                name=r.name,
                resource_type=r.resource_type,
                provenance=[r.provenance],
            )
            for r in topology.resources
        ]

        for system in systems:
            await self._catalog.upsert_system(system)
        for component in components:
            await self._catalog.upsert_component(component)
        for interface in interfaces:
            await self._catalog.upsert_interface(interface)
        for resource in resources:
            await self._catalog.upsert_resource(resource)

        return TopologyDiscoveryResult(
            topology=topology,
            claims=claims,
            systems=systems,
            components=components,
            interfaces=interfaces,
            resources=resources,
        )

    @staticmethod
    def _systems(project_id: ProjectId, components: list[SoftwareComponent]) -> list[System]:
        if not components:
            return []
        system = System(
            project_id=project_id,
            name="default",
            component_ids=[c.id for c in components],
        )
        return [system]

    def _interfaces(
        self,
        project_id: ProjectId,
        components: list[SoftwareComponent],
        topology: DiscoveredTopology,
    ) -> list[Interface]:
        del project_id
        by_name = {c.name: c for c in components}
        interfaces: list[Interface] = []
        for candidate in topology.interfaces:
            component = by_name.get(candidate.component_name)
            if component is None:
                continue
            interfaces.append(
                Interface(
                    component_id=component.id,
                    type=_interface_type(candidate.interface_type),
                    name=candidate.name,
                    schema_ref=candidate.schema_ref,
                )
            )
        return interfaces


def _interface_type(value: object) -> InterfaceType:
    if isinstance(value, InterfaceType):
        return value
    try:
        return InterfaceType(str(value))
    except ValueError:
        return InterfaceType.REST


__all__ = ["TopologyDiscoveryResult", "TopologyDiscoveryService"]
