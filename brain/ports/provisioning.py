"""Project provisioning ports (Phase 1.2).

Provider-neutral surfaces for *creating* external projects/spaces, kept
separate from the read/operation ports (``WorkManagementPort``,
``SourceControlPort``, ``DocumentationPort``) so those contracts stay clean.
``ExternalProjects`` carries the identifiers of external projects that already
exist and should be linked (bootstrap), never created.

The canonical Brain project stays the primary identity; the refs returned by
these ports become ``ExternalReference`` records on it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from brain.domain.external_reference import ExternalReference


class ExternalProjects(BaseModel):
    """Existing external project identifiers to link (bootstrap case)."""

    work_management: str | None = None
    source_control: str | None = None
    documentation: str | None = None


@runtime_checkable
class SourceControlProvisioningPort(Protocol):
    async def create_project(
        self, name: str, description: str | None = None
    ) -> ExternalReference: ...


@runtime_checkable
class DocumentationProvisioningPort(Protocol):
    async def create_space(self, name: str) -> ExternalReference: ...


__all__ = [
    "DocumentationProvisioningPort",
    "ExternalProjects",
    "SourceControlProvisioningPort",
]
