"""XWiki space -> Brain project resolution (Step 3), durable watermarks
(Step 5) and documentation reconciliation (Step 6).

An XWiki page reference (``ADAS.Requirements.Braking``) is resolved to a
canonical Brain project through the project's ``ExternalReference(xwiki,
space, <space>)`` records.  The Brain project remains canonical; an unmapped
page is never silently assigned to another project (it is reported and left
eligible for retry).

Watermarks reuse the shared ``SyncWatermarkRepository`` (the same durable
infrastructure as work-management pull sync): one cursor per
``(project, space)`` pair, so restarts resume from the persisted position.

Reconciliation orchestrates one space cycle: watermark -> changed pages ->
fetch -> canonical ingestion -> advance (only on zero failures).  Parsing and
document persistence stay in ``DocumentIngestionService``; this module never
duplicates them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from brain.application.document_ingestion import DocumentIngestionService
from brain.application.xwiki_sync import XWikiMappingService
from brain.domain.documents import DocumentType
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ProjectId
from brain.domain.projects import Project
from brain.domain.sync_watermark import ProviderSyncWatermark
from brain.ports.documentation import DocumentationPort
from brain.ports.repositories import ProjectRepository
from brain.ports.sync_watermark import SyncWatermarkRepository

logger = logging.getLogger(__name__)

_SEPARATOR_RE = re.compile(r"[/.]")
_WIKI_PREFIX_RE = re.compile(r"^[^.:]+:")

XWIKI_PROVIDER = "xwiki"


def extract_space(page_id: str) -> str:
    """Extract the wiki space from a page reference.

    Accepts dotted references (``ADAS.Requirements.Braking`` -> ``ADAS``),
    slash references (``xwiki/Main/WebHome`` -> ``Main``) and wiki-prefixed
    full references (``xwiki:ADAS.WebHome`` -> ``ADAS``).
    """
    raw = _WIKI_PREFIX_RE.sub("", page_id.strip())
    parts = [p for p in _SEPARATOR_RE.split(raw) if p]
    if not parts:
        return raw
    if "/" in raw and len(parts) >= 3:
        # Slash form: <wiki>/<space>/<page>
        return parts[1]
    return parts[0]


@dataclass(frozen=True)
class XWikiPageProjectResolution:
    """Result of resolving an XWiki page reference to a Brain project."""

    page_id: str
    space: str
    project: Project | None = None

    @property
    def resolved(self) -> bool:
        return self.project is not None


class XWikiProjectResolver:
    """Resolves XWiki page references to canonical Brain projects."""

    def __init__(self, *, projects: ProjectRepository) -> None:
        self._projects = projects

    async def resolve(self, ref: ExternalReference) -> XWikiPageProjectResolution:
        """Resolve a page reference to the owning Brain project.

        The mapping is ``ExternalReference(xwiki, space, <space>)`` on the
        project; unmapped pages resolve to ``project=None``.
        """
        page_id = ref.external_id
        space = extract_space(page_id)
        project = await self._projects.find_by_external_ref("xwiki", space, "space")
        return XWikiPageProjectResolution(page_id=page_id, space=space, project=project)

    async def resolve_project_id(self, ref: ExternalReference) -> ProjectId | None:
        resolution = await self.resolve(ref)
        return resolution.project.id if resolution.project is not None else None


class XWikiWatermarks:
    """Durable per-(project, space) documentation sync cursors (Step 5).

    Reuses the shared ``SyncWatermarkRepository``; the watermark is advanced
    only after a cycle completes without ingestion failures, so failed pages
    remain eligible for retry on the next reconciliation pass.
    """

    def __init__(self, *, watermarks: SyncWatermarkRepository) -> None:
        self._watermarks = watermarks

    @staticmethod
    def sync_key(project_id: ProjectId, space: str) -> str:
        return f"project:{project_id}:space:{space}"

    async def since(self, project_id: ProjectId, space: str) -> datetime | None:
        """Return the last successful sync timestamp, or ``None`` (initial)."""
        watermark = await self._watermarks.get_or_create(
            XWIKI_PROVIDER, self.sync_key(project_id, space)
        )
        return watermark.last_synced_at

    async def advance(
        self,
        project_id: ProjectId,
        space: str,
        *,
        synced_at: datetime | None = None,
        last_external_id: str | None = None,
    ) -> ProviderSyncWatermark:
        """Persist the new cursor after a successful cycle."""
        watermark = await self._watermarks.get_or_create(
            XWIKI_PROVIDER, self.sync_key(project_id, space)
        )
        updated = watermark.model_copy(
            update={
                "last_synced_at": synced_at or datetime.now(UTC),
                "last_external_id": last_external_id or watermark.last_external_id,
                "updated_at": datetime.now(UTC),
            }
        )
        return await self._watermarks.save(updated)


@dataclass
class XWikiSpaceSyncResult:
    """Outcome of one (project, space) reconciliation cycle (doc §13/§17)."""

    project_id: ProjectId
    space: str
    since: datetime | None = None
    discovered: int = 0
    ingested: int = 0
    unchanged: int = 0
    failed: int = 0
    details: list[str] = field(default_factory=list)


class XWikiDocumentationSyncService:
    """Orchestrates one documentation reconciliation cycle per (project, space).

    Orchestration only: changed-page discovery, project resolution, fetch and
    canonical ingestion are delegated; parsing/persistence logic lives in
    ``DocumentIngestionService`` (fix-plan §1/§19).  The watermark advances
    only when the cycle had zero failures, so failed pages are retried.
    """

    def __init__(
        self,
        *,
        resolver: XWikiProjectResolver,
        watermarks: XWikiWatermarks,
        ingestion: DocumentIngestionService,
        mapping: XWikiMappingService | None = None,
    ) -> None:
        self._resolver = resolver
        self._watermarks = watermarks
        self._ingestion = ingestion
        self._mapping = mapping

    async def sync_project_spaces(
        self,
        port: DocumentationPort,
        project: Project,
    ) -> list[XWikiSpaceSyncResult]:
        """Reconcile every XWiki space mapped to the project."""
        spaces = [
            ref.external_id
            for ref in project.external_refs
            if ref.provider == XWIKI_PROVIDER and ref.external_type == "space"
        ]
        return [await self.sync_space(port, project, space) for space in spaces]

    async def sync_space(
        self,
        port: DocumentationPort,
        project: Project,
        space: str,
    ) -> XWikiSpaceSyncResult:
        """Reconcile one mapped space: discover, fetch, ingest, advance."""
        since = await self._watermarks.since(project.id, space)
        refs = await port.list_changed_documents(since, spaces=[space])
        result = XWikiSpaceSyncResult(
            project_id=project.id,
            space=space,
            since=since,
            discovered=len(refs),
        )
        failed = False
        for ref in refs:
            try:
                resolution = await self._resolver.resolve(ref)
                if not resolution.resolved:
                    result.failed += 1
                    result.details.append(f"{ref.external_id}: unmapped space {resolution.space}")
                    failed = True
                    continue
                artifact = await port.fetch_document(ref)
                document_type = self._document_type(ref)
                resolved_project = resolution.project
                assert resolved_project is not None
                ingested = await self._ingestion.ingest(
                    artifact,
                    project_id=resolved_project.id,
                    document_type=document_type,
                )
                if ingested.created_new_version:
                    result.ingested += 1
                else:
                    result.unchanged += 1
            except Exception as exc:  # noqa: BLE001 - one bad page must not
                # abort the whole cycle (doc §13)
                result.failed += 1
                result.details.append(f"{ref.external_id}: {type(exc).__name__}: {exc}")
                failed = True

        if not failed and (result.discovered > 0 or since is not None):
            # Advance only when the cycle produced results (or resumed from an
            # existing watermark).  An initial sync that discovers nothing is
            # suspicious (transient index/network issue) and must be retried.
            await self._watermarks.advance(
                project.id,
                space,
                last_external_id=refs[-1].external_id if refs else None,
            )
        return result

    def _document_type(self, ref: ExternalReference) -> DocumentType | None:
        if self._mapping is None:
            return None
        return self._mapping.document_type_for_page({"id": ref.external_id})


__all__ = [
    "XWikiDocumentationSyncService",
    "XWikiPageProjectResolution",
    "XWikiProjectResolver",
    "XWikiSpaceSyncResult",
    "XWikiWatermarks",
    "extract_space",
]
