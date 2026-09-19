"""Work-management bootstrap + pull snapshot port.

Provider-neutral surface for importing an existing external project into the
brain (bootstrap) and for periodic pull reconciliation.  The bootstrap and
pull services depend only on this protocol; the OpenProject adapter implements
it by normalizing raw provider payloads with the same parsers used by
webhooks, so provider shapes never reach application code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from brain.application.openproject_parser import OpenProjectWorkItemSnapshot


class ProviderProject(BaseModel):
    """Canonical project snapshot from a work-management provider."""

    external_id: str
    name: str
    identifier: str = ""
    description: str = ""
    active: bool = True
    parent_external_id: str | None = None


class ProviderActivity(BaseModel):
    """Canonical comment/activity snapshot from a work-management provider."""

    external_id: str
    author_name: str = ""
    text: str = ""
    created_at: str | None = None


@runtime_checkable
class WorkManagementBootstrapPort(Protocol):
    async def list_projects(self) -> list[ProviderProject]: ...

    async def list_work_packages(
        self,
        project_external_id: str,
        *,
        offset: int = 1,
        page_size: int = 100,
    ) -> list[OpenProjectWorkItemSnapshot]: ...

    async def list_changed_work_packages(
        self,
        since: datetime,
        *,
        offset: int = 1,
        page_size: int = 100,
    ) -> list[OpenProjectWorkItemSnapshot]: ...

    async def get_work_package_snapshot(
        self, external_id: str
    ) -> OpenProjectWorkItemSnapshot | None: ...

    async def list_activities(self, work_package_external_id: str) -> list[ProviderActivity]: ...


__all__ = ["ProviderActivity", "ProviderProject", "WorkManagementBootstrapPort"]
