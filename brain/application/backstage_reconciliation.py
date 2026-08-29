"""Backstage topology reconciliation (Phase 36).

Compares human-declared topology (Backstage) with brain-discovered topology
(derived catalog) without overwriting disagreements (Task 36.3), and creates
CONFLICT / DEPENDENCY_DISCOVERED observations when the declared catalog and
the discovered topology disagree (Task 36.4).
"""

from __future__ import annotations

import logging

from brain.application.observations import ObservationService
from brain.bootstrap.container import BrainContainer
from brain.domain.observations import ObservationType
from brain.domain.projects import Project
from brain.domain.software_model import SoftwareComponent
from brain.ports.software_catalog import SoftwareCatalogPort

logger = logging.getLogger(__name__)


class BackstageReconciliationResult:
    """Outcome of reconciling declared vs discovered topology."""

    def __init__(self) -> None:
        self.checked_components = 0
        self.conflicts: list[str] = []
        self.dependencies_discovered: list[str] = []
        self.observations_created: list[str] = []


class BackstageReconciliationService:
    """Reconciles Backstage-declared topology with the derived catalog."""

    def __init__(
        self,
        *,
        backstage: SoftwareCatalogPort | None,
        container: BrainContainer,
        observations: ObservationService,
    ) -> None:
        self._backstage = backstage
        self._container = container
        self._observations = observations

    async def reconcile(self, project: Project) -> BackstageReconciliationResult:
        result = BackstageReconciliationResult()
        if self._backstage is None:
            return result

        declared = {
            component.name: component
            for component in await self._backstage.list_components(project)
        }
        discovered = {
            component.name: component
            for component in await self._container.repositories.software_catalog.list_components(
                project.id
            )
        }

        for name, declared_component in declared.items():
            result.checked_components += 1
            discovered_component = discovered.get(name)
            if discovered_component is None:
                result.conflicts.append(
                    f"component '{name}' declared in Backstage but not discovered by the brain"
                )
                continue
            if _type_mismatch(declared_component, discovered_component):
                result.conflicts.append(
                    f"component '{name}' type differs: declared "
                    f"{declared_component.component_type.value} vs discovered "
                    f"{discovered_component.component_type.value}"
                )
            else:
                # Agreement: refresh the declared provenance on the canonical row.
                discovered_component = discovered_component.model_copy(
                    update={"lifecycle": declared_component.lifecycle}
                )
                await self._container.repositories.software_catalog.upsert_component(
                    discovered_component
                )

        # Dependencies: Backstage-declared dependencies not seen by discovery.
        dependency_lister = getattr(self._backstage, "list_dependencies", None)
        if dependency_lister is not None:
            for source, target in await dependency_lister():
                if source not in declared and target not in declared:
                    result.dependencies_discovered.append(f"{source} -> {target}")

        for conflict in result.conflicts:
            observation = await self._observations.create(
                project_id=project.id,
                observation_type=ObservationType.CONFLICT,
                title="Catalog conflict",
                body=conflict,
                dedup_key=f"backstage-conflict:{project.id}:{conflict[:100]}",
            )
            result.observations_created.append(str(observation.id))
        for dependency in result.dependencies_discovered:
            observation = await self._observations.create(
                project_id=project.id,
                observation_type=ObservationType.DEPENDENCY_DISCOVERED,
                title="Dependency not covered by discovery",
                body=dependency,
                dedup_key=f"backstage-dependency:{project.id}:{dependency}",
            )
            result.observations_created.append(str(observation.id))
        return result


def _type_mismatch(declared: SoftwareComponent, discovered: SoftwareComponent) -> bool:
    return declared.component_type != discovered.component_type


__all__ = [
    "BackstageReconciliationResult",
    "BackstageReconciliationService",
]
