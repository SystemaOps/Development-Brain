"""Derived SoftwareCatalogPort (Task 15.4).

Uses the brain-discovered topology as the default ``SoftwareCatalogPort``:
components/interfaces/resources come from the brain's own catalog repository,
so the brain works with no external catalog at all.
"""

from __future__ import annotations

from brain.adapters.topology.catalog import DerivedSoftwareCatalog
from brain.domain.projects import Project
from brain.domain.software_model import Interface, Resource, SoftwareComponent
from brain.ports.software_catalog import SoftwareCatalogPort


class DerivedCatalogPortAdapter(SoftwareCatalogPort):
    """Exposes the brain's derived catalog behind the SoftwareCatalogPort."""

    def __init__(self, derived: DerivedSoftwareCatalog) -> None:
        self._derived = derived

    async def list_components(self, project: Project) -> list[SoftwareComponent]:
        return await self._derived.list_components(project)

    async def list_interfaces(self, project: Project) -> list[Interface]:
        return await self._derived.list_interfaces(project)

    async def list_resources(self, project: Project) -> list[Resource]:
        return await self._derived.list_resources(project)


__all__ = ["DerivedCatalogPortAdapter"]
