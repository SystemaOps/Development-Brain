"""Software catalog port (Backstage / ServiceNow / derived).

A null or derived implementation must exist so the brain works without an
external catalog.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from brain.domain.projects import Project
from brain.domain.software_model import Interface, Resource, SoftwareComponent


@runtime_checkable
class SoftwareCatalogPort(Protocol):
    async def list_components(self, project: Project) -> list[SoftwareComponent]: ...

    async def list_interfaces(self, project: Project) -> list[Interface]: ...

    async def list_resources(self, project: Project) -> list[Resource]: ...
