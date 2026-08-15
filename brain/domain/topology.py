"""Software topology discovery domain model (Phase 6).

Discovery turns a :class:`~brain.domain.repository_scan.RepositorySnapshot`
into candidates: components, interfaces, resources and dependencies.  Every
candidate carries provenance (who found it, how confident we are) so later
stages can reconcile multiple claims -- declared catalog metadata vs.
discovered facts -- without silently overwriting disagreement.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.knowledge import KnowledgeConfidence, KnowledgeEvidence
from brain.domain.software_model import (
    ComponentType,
    InterfaceType,
    ResourceType,
)


class CandidateKind(StrEnum):
    COMPONENT = "component"
    INTERFACE = "interface"
    RESOURCE = "resource"
    DEPENDENCY = "dependency"


class ComponentCandidate(BaseModel):
    """A discovered software component (service, library, worker, ...)."""

    name: str
    component_type: ComponentType = ComponentType.LIBRARY
    repository_id: RepositoryId
    revision: str
    source_paths: list[str] = Field(default_factory=list)
    provenance: KnowledgeEvidence
    metadata: dict[str, object] = Field(default_factory=dict)


class InterfaceCandidate(BaseModel):
    """A discovered API/interface (REST, GraphQL, gRPC, message topic)."""

    name: str
    interface_type: InterfaceType = InterfaceType.REST
    component_name: str
    schema_ref: str | None = None
    repository_id: RepositoryId
    revision: str
    source_paths: list[str] = Field(default_factory=list)
    provenance: KnowledgeEvidence


class ResourceCandidate(BaseModel):
    """A discovered external/infrastructure resource (Postgres, Redis, ...)."""

    name: str
    resource_type: ResourceType = ResourceType.EXTERNAL_SERVICE
    repository_id: RepositoryId
    revision: str
    source_paths: list[str] = Field(default_factory=list)
    provenance: KnowledgeEvidence


class DependencyCandidate(BaseModel):
    """A discovered dependency between two topology entities."""

    source: str
    target: str
    relation: str = "DEPENDS_ON"
    project_id: ProjectId | None = None
    repository_id: RepositoryId
    revision: str
    source_paths: list[str] = Field(default_factory=list)
    provenance: KnowledgeEvidence


class DiscoveredTopology(BaseModel):
    """The aggregate output of one discovery pass over a repository snapshot."""

    repository_id: RepositoryId
    revision: str
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    components: list[ComponentCandidate] = Field(default_factory=list)
    interfaces: list[InterfaceCandidate] = Field(default_factory=list)
    resources: list[ResourceCandidate] = Field(default_factory=list)
    dependencies: list[DependencyCandidate] = Field(default_factory=list)

    def merge(self, other: DiscoveredTopology) -> None:
        """Combine another discovery pass into this one (idempotent by identity)."""
        self.components = _merge_components(self.components, other.components)
        self.interfaces = _merge_interfaces(self.interfaces, other.interfaces)
        self.resources = _merge_resources(self.resources, other.resources)
        self.dependencies = _merge_dependencies(self.dependencies, other.dependencies)


def _merge_components(
    existing: list[ComponentCandidate], incoming: list[ComponentCandidate]
) -> list[ComponentCandidate]:
    seen = {c.name for c in existing}
    for item in incoming:
        if item.name not in seen:
            seen.add(item.name)
            existing.append(item)
    return existing


def _merge_interfaces(
    existing: list[InterfaceCandidate], incoming: list[InterfaceCandidate]
) -> list[InterfaceCandidate]:
    seen = {(i.component_name, i.name) for i in existing}
    for item in incoming:
        key = (item.component_name, item.name)
        if key not in seen:
            seen.add(key)
            existing.append(item)
    return existing


def _merge_resources(
    existing: list[ResourceCandidate], incoming: list[ResourceCandidate]
) -> list[ResourceCandidate]:
    seen = {r.name for r in existing}
    for item in incoming:
        if item.name not in seen:
            seen.add(item.name)
            existing.append(item)
    return existing


def _merge_dependencies(
    existing: list[DependencyCandidate], incoming: list[DependencyCandidate]
) -> list[DependencyCandidate]:
    seen = {(d.source, d.relation, d.target) for d in existing}
    for item in incoming:
        key = (item.source, item.relation, item.target)
        if key not in seen:
            seen.add(key)
            existing.append(item)
    return existing


class TopologyClaim(BaseModel):
    """A single claim about a topology entity, for reconciliation.

    Reconciliation keeps multiple claims for one conceptual entity instead of
    overwriting disagreement: a component may be DECLARED as a library in a
    catalog while discovery INFERS it is a service.  The strongest claim
    (declared > observed > discovered > inferred, then confidence) wins while
    the rest are preserved.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    entity_kind: CandidateKind
    entity_name: str
    attribute: str = "component_type"
    value: str
    repository_id: RepositoryId
    revision: str
    origin: str = "discovered"
    confidence: KnowledgeConfidence = KnowledgeConfidence.MEDIUM
    provenance: KnowledgeEvidence
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def sort_rank(self) -> int:
        """Lower rank wins during reconciliation (declared first)."""
        order = {"declared": 0, "observed": 1, "discovered": 2, "inferred": 3}
        return order.get(self.origin, 4)


__all__ = [
    "CandidateKind",
    "ComponentCandidate",
    "DependencyCandidate",
    "DiscoveredTopology",
    "InterfaceCandidate",
    "ResourceCandidate",
    "TopologyClaim",
    "TopologyReconciler",
]


class TopologyReconciler:
    """Reconcile candidate discovery output into per-entity claims (Task 6.7).

    Every candidate becomes a claim; reconciliation keeps all claims so
    declared/discovered/inferred facts about the same entity are preserved
    instead of overwritten.  ``reconcile`` resolves the winning value per
    entity (declared first, then confidence).
    """

    def claims(self, topology: DiscoveredTopology) -> list[TopologyClaim]:
        claims: list[TopologyClaim] = []
        for component in topology.components:
            claims.append(
                TopologyClaim(
                    entity_kind=CandidateKind.COMPONENT,
                    entity_name=component.name,
                    attribute="component_type",
                    value=component.component_type.value,
                    repository_id=component.repository_id,
                    revision=component.revision,
                    origin=component.provenance.origin.value,
                    confidence=component.provenance.confidence,
                    provenance=component.provenance,
                )
            )
        for interface in topology.interfaces:
            claims.append(
                TopologyClaim(
                    entity_kind=CandidateKind.INTERFACE,
                    entity_name=f"{interface.component_name}:{interface.name}",
                    attribute="interface_type",
                    value=interface.interface_type.value,
                    repository_id=interface.repository_id,
                    revision=interface.revision,
                    origin=interface.provenance.origin.value,
                    confidence=interface.provenance.confidence,
                    provenance=interface.provenance,
                )
            )
        for resource in topology.resources:
            claims.append(
                TopologyClaim(
                    entity_kind=CandidateKind.RESOURCE,
                    entity_name=resource.name,
                    attribute="resource_type",
                    value=resource.resource_type.value,
                    repository_id=resource.repository_id,
                    revision=resource.revision,
                    origin=resource.provenance.origin.value,
                    confidence=resource.provenance.confidence,
                    provenance=resource.provenance,
                )
            )
        return claims

    def reconcile(self, claims: list[TopologyClaim]) -> dict[tuple[CandidateKind, str], str]:
        winners: dict[tuple[CandidateKind, str], str] = {}
        best: dict[tuple[CandidateKind, str], TopologyClaim] = {}
        for claim in claims:
            key = (claim.entity_kind, claim.entity_name)
            current = best.get(key)
            if current is None or _beats(claim, current):
                best[key] = claim
                winners[key] = claim.value
        return winners


def _beats(candidate: TopologyClaim, current: TopologyClaim) -> bool:
    if candidate.sort_rank != current.sort_rank:
        return candidate.sort_rank < current.sort_rank
    return candidate.confidence.score() > current.confidence.score()
