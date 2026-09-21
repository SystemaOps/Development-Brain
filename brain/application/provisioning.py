"""Project provisioning service (Phase 3).

Orchestrates the project-creation workflows from
``docs/cli/project_creation_provisioning.md`` so CLI, API, and agents share
one implementation:

- ``create_canonical``  — brain project only (no external systems touched);
- ``create_connected``  — canonical project + provisioned external projects;
- ``provision``         — create missing external projects for an existing
  canonical project (each configured provider, best-effort);
- ``bootstrap``         — link external projects that ALREADY exist
  (never create), idempotently.

The canonical Brain project stays the primary identity; provider results are
recorded as ``ExternalReference`` on it.  A provider failure is captured in
``details`` and never rolls back the canonical project.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from brain.application.openproject_bootstrap import OpenProjectProjectBootstrapService
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ProjectId
from brain.domain.projects import Project
from brain.ports.event_bus import EventBus
from brain.ports.provisioning import (
    DocumentationProvisioningPort,
    ExternalProjects,
    SourceControlProvisioningPort,
)
from brain.ports.repositories import ProjectRepository
from brain.ports.work_management import WorkManagementPort

logger = logging.getLogger(__name__)


@dataclass
class ProvisioningResult:
    """Outcome of a provisioning/linking run."""

    project: Project
    refs_added: list[ExternalReference] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


class ProjectProvisioningService:
    """Create and link projects across the brain and external systems."""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        work_management: WorkManagementPort | None,
        source_control: SourceControlProvisioningPort | None,
        documentation: DocumentationProvisioningPort | None,
        bootstrap: OpenProjectProjectBootstrapService | None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._projects = projects
        self._work_management = work_management
        self._source_control = source_control
        self._documentation = documentation
        self._bootstrap = bootstrap
        self._event_bus = event_bus

    # --- create ------------------------------------------------------------

    async def create_canonical(
        self,
        name: str,
        description: str | None = None,
    ) -> Project:
        """Create only the canonical Brain project."""
        project = Project(name=name, description=description)
        return await self._projects.create(project)

    async def create_connected(
        self,
        name: str,
        description: str | None = None,
    ) -> ProvisioningResult:
        """Create a brand-new project ecosystem (canonical + externals)."""
        project = await self.create_canonical(name, description)
        return await self.provision(project.id)

    # --- provision (create missing external projects) ----------------------

    async def provision(self, project_id: ProjectId) -> ProvisioningResult:
        """Create external projects for a canonical project (best-effort)."""
        project = await self._load_project(project_id)
        result = ProvisioningResult(project=project)
        await self._try_provide(
            result,
            label="work management",
            provider=self._work_management,
            create=lambda: self._create_work_management(project),
        )
        await self._try_provide(
            result,
            label="source control",
            provider=self._source_control,
            create=lambda: self._source_control.create_project(  # type: ignore[union-attr]
                project.name, project.description or None
            ),
        )
        await self._try_provide(
            result,
            label="documentation",
            provider=self._documentation,
            create=lambda: self._documentation.create_space(  # type: ignore[union-attr]
                _space_name(project.name)
            ),
        )
        return await self._persist_refs(result)

    async def _create_work_management(self, project: Project) -> ExternalReference:
        wm = self._work_management
        assert wm is not None
        return await wm.create_project(project.name, project.description or None)

    # --- bootstrap (link existing external projects) -----------------------

    async def bootstrap(
        self,
        project_id: ProjectId,
        external: ExternalProjects,
    ) -> ProvisioningResult:
        """Link external projects that already exist; never create them."""
        project = await self._load_project(project_id)
        result = ProvisioningResult(project=project)

        candidates: list[tuple[str, str | None, str]] = [
            ("openproject", external.work_management, "project"),
            ("gitlab", external.source_control, "project"),
            ("xwiki", external.documentation, "space"),
        ]
        for provider, external_id, external_type in candidates:
            if not external_id:
                continue
            ref = ExternalReference(
                provider=provider,
                external_id=external_id,
                external_type=external_type,
            )
            if any(
                r.provider == ref.provider
                and r.external_type == ref.external_type
                and r.external_id == ref.external_id
                for r in project.external_refs
            ):
                result.details.append(f"{provider}: already linked ({external_id})")
                continue
            project.external_refs = [*project.external_refs, ref]
            result.refs_added.append(ref)
            result.details.append(f"{provider}: linked existing {external_id}")

        return await self._persist_refs(result)

    # --- helpers ------------------------------------------------------------

    async def _load_project(self, project_id: ProjectId) -> Project:
        project = await self._projects.get(project_id)
        if project is None:
            raise ValueError(f"project {project_id} not found")
        return project

    async def _try_provide(
        self,
        result: ProvisioningResult,
        *,
        label: str,
        provider: object | None,
        create: Callable[[], Awaitable[ExternalReference]],
    ) -> None:
        if provider is None:
            result.details.append(f"{label}: not configured, skipped")
            return
        try:
            ref = await create()
            result.refs_added.append(ref)
            result.details.append(f"{label}: created {ref.external_id}")
        except NotImplementedError:
            result.details.append(f"{label}: creation not supported by provider")
        except Exception as exc:  # noqa: BLE001 - best-effort provisioning
            logger.warning("provisioning %s failed: %s", label, exc)
            result.details.append(f"{label}: provisioning failed ({exc})")

    async def _persist_refs(self, result: ProvisioningResult) -> ProvisioningResult:
        if not result.refs_added:
            return result
        merged = list(result.project.external_refs)
        for ref in result.refs_added:
            if not any(
                r.provider == ref.provider
                and r.external_type == ref.external_type
                and r.external_id == ref.external_id
                for r in merged
            ):
                merged.append(ref)
        updated = result.project.model_copy(update={"external_refs": merged})
        stored = await self._projects.update(updated)
        result.project = stored
        return result


def _space_name(project_name: str) -> str:
    """Derive an XWiki space name from a project name."""
    chars = []
    for ch in project_name.strip():
        if ch.isalnum():
            chars.append(ch)
    space = "".join(chars)
    return space or "Project"


__all__ = ["ProjectProvisioningService", "ProvisioningResult"]
