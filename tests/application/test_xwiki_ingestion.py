"""Step 3 tests: XWiki space -> Brain project mapping.

Per the fix plan §16:

- mapped space (``ExternalReference(xwiki, space, ADAS)``) resolves the page;
- unknown space resolves unmapped (never silently assigned elsewhere);
- dotted, slash and wiki-prefixed page references normalize to the space.
"""

from __future__ import annotations

import uuid

from brain.adapters.in_memory.repositories import InMemoryProjectRepository
from brain.application.xwiki_ingestion import (
    XWikiProjectResolver,
    extract_space,
)
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ProjectId
from brain.domain.projects import Project


def _ref(page_id: str) -> ExternalReference:
    return ExternalReference(
        provider="xwiki",
        external_id=page_id,
        external_type="page",
        namespace="xwiki",
    )


def test_extract_space_normalizes_references() -> None:
    assert extract_space("ADAS.Requirements.Braking") == "ADAS"
    assert extract_space("ADAS.WebHome") == "ADAS"
    assert extract_space("Main.WebHome") == "Main"
    assert extract_space("xwiki/Main/WebHome") == "Main"
    assert extract_space("xwiki:ADAS.WebHome") == "ADAS"
    assert extract_space("WebHome") == "WebHome"


async def test_resolve_mapped_space_to_project() -> None:
    projects = InMemoryProjectRepository()
    project = Project(
        name="ADAS Platform",
        external_refs=[
            ExternalReference(provider="xwiki", external_id="ADAS", external_type="space")
        ],
    )
    await projects.create(project)

    resolver = XWikiProjectResolver(projects=projects)
    resolution = await resolver.resolve(_ref("ADAS.Requirements.Braking"))
    assert resolution.space == "ADAS"
    assert resolution.resolved is True
    assert resolution.project is not None
    assert resolution.project.id == project.id


async def test_resolve_unmapped_space_is_rejected() -> None:
    projects = InMemoryProjectRepository()
    project = Project(
        name="ADAS Platform",
        external_refs=[
            ExternalReference(provider="xwiki", external_id="ADAS", external_type="space")
        ],
    )
    await projects.create(project)

    resolver = XWikiProjectResolver(projects=projects)
    resolution = await resolver.resolve(_ref("OtherSpace.PageName"))
    assert resolution.resolved is False
    assert resolution.project is None
    assert resolution.space == "OtherSpace"


async def test_resolve_does_not_match_other_provider_refs() -> None:
    """A project linked only via openproject/gitlab refs is never matched."""
    projects = InMemoryProjectRepository()
    project = Project(
        name="Only OpenProject",
        external_refs=[
            ExternalReference(provider="openproject", external_id="42", external_type="project")
        ],
    )
    await projects.create(project)

    resolver = XWikiProjectResolver(projects=projects)
    resolution = await resolver.resolve(_ref("ADAS.WebHome"))
    assert resolution.resolved is False


async def test_resolve_project_id_returns_none_when_unmapped() -> None:
    projects = InMemoryProjectRepository()
    resolver = XWikiProjectResolver(projects=projects)
    assert await resolver.resolve_project_id(_ref("Nope.Page")) is None
    assert await resolver.resolve_project_id(_ref(uuid.uuid4().hex + ".Page")) is None


# --- Step 5: durable watermarks --------------------------------------------


def _project_id() -> ProjectId:
    return ProjectId(uuid.uuid4())


async def test_watermark_initial_since_is_none() -> None:
    from brain.adapters.in_memory.repositories import InMemorySyncWatermarkRepository
    from brain.application.xwiki_ingestion import XWikiWatermarks

    watermarks = XWikiWatermarks(watermarks=InMemorySyncWatermarkRepository())
    project_id = _project_id()
    assert await watermarks.since(project_id, "ADAS") is None


async def test_watermark_advance_persists_and_resumes() -> None:
    from datetime import UTC, datetime, timedelta

    from brain.adapters.in_memory.repositories import InMemorySyncWatermarkRepository
    from brain.application.xwiki_ingestion import XWikiWatermarks

    repository = InMemorySyncWatermarkRepository()
    watermarks = XWikiWatermarks(watermarks=repository)
    project_id = _project_id()
    synced_at = datetime.now(UTC) - timedelta(minutes=5)

    await watermarks.advance(project_id, "ADAS", synced_at=synced_at, last_external_id="ADAS.P1")

    # A fresh helper over the same durable repository resumes from the cursor
    # (simulates a process restart).
    resumed = XWikiWatermarks(watermarks=repository)
    assert await resumed.since(project_id, "ADAS") == synced_at


async def test_watermark_is_isolated_per_project_and_space() -> None:
    from datetime import UTC, datetime

    from brain.adapters.in_memory.repositories import InMemorySyncWatermarkRepository
    from brain.application.xwiki_ingestion import XWikiWatermarks

    watermarks = XWikiWatermarks(watermarks=InMemorySyncWatermarkRepository())
    project_a = _project_id()
    project_b = _project_id()
    now = datetime.now(UTC)

    await watermarks.advance(project_a, "ADAS", synced_at=now)
    assert await watermarks.since(project_a, "ADAS") == now
    assert await watermarks.since(project_a, "Other") is None
    assert await watermarks.since(project_b, "ADAS") is None


async def test_watermark_sync_key_format() -> None:
    from brain.application.xwiki_ingestion import XWikiWatermarks

    project_id = _project_id()
    assert XWikiWatermarks.sync_key(project_id, "ADAS") == f"project:{project_id}:space:ADAS"
