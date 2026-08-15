"""Derived software catalog (Task 6.8).

Exposes list systems / components / interfaces / resources / dependencies
*without* requiring Backstage or any external catalog.  It reads the reconciled
canonical entities persisted through :class:`SoftwareCatalogRepository` and
answers queries directly from brain-owned state.
"""

from __future__ import annotations

from brain.domain.projects import Project
from brain.domain.software_model import (
    Interface,
    Resource,
    SoftwareComponent,
    System,
)
from brain.ports.topology import SoftwareCatalogRepository


class DerivedSoftwareCatalog:
    """Read API over brain-owned catalog state."""

    def __init__(self, catalog: SoftwareCatalogRepository) -> None:
        self._catalog = catalog

    async def list_components(self, project: Project) -> list[SoftwareComponent]:
        return await self._catalog.list_components(project.id)

    async def list_interfaces(self, project: Project) -> list[Interface]:
        return await self._catalog.list_interfaces(project.id)

    async def list_resources(self, project: Project) -> list[Resource]:
        return await self._catalog.list_resources(project.id)

    async def list_systems(self, project: Project) -> list[System]:
        return await self._catalog.list_systems(project.id)

    async def get_dependencies(self, project: Project, component_name: str) -> list[str]:
        return await self._catalog.list_dependencies(project.id, component_name)


__all__ = ["DerivedSoftwareCatalog"]
