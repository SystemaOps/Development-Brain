"""Null/derived software catalog.

The default when no external catalog is configured: the brain works entirely
from discovered topology.
"""

from __future__ import annotations

from brain.domain.projects import Project
from brain.domain.software_model import Interface, Resource, SoftwareComponent


class NullSoftwareCatalog:
    async def list_components(self, project: Project) -> list[SoftwareComponent]:
        del project
        return []

    async def list_interfaces(self, project: Project) -> list[Interface]:
        del project
        return []

    async def list_resources(self, project: Project) -> list[Resource]:
        del project
        return []
