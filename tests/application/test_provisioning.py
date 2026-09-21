"""Phase 3/6 tests: project provisioning service.

``ProjectProvisioningService`` implements the two creation workflows from
``docs/cli/project_creation_provisioning.md``:

- ``create_connected`` — brand-new project ecosystem (canonical + externals);
- ``bootstrap`` — link external projects that already exist (never create).

Provider creation is best-effort: an unconfigured provider is skipped, a
failing provider never blocks the others or the canonical project.
"""

from __future__ import annotations

import uuid

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.repositories import InMemoryProjectRepository
from brain.application.provisioning import ProjectProvisioningService
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ProjectId
from brain.ports.provisioning import ExternalProjects


class _FakeWorkManagement:
    def __init__(self, *, fail: bool = False, unsupported: bool = False) -> None:
        self.fail = fail
        self.unsupported = unsupported
        self.created: list[str] = []

    async def create_project(self, name: str, description: str | None = None) -> ExternalReference:
        if self.fail:
            raise RuntimeError("provider boom")
        if self.unsupported:
            raise NotImplementedError
        self.created.append(name)
        return ExternalReference(provider="openproject", external_id="p-1", external_type="project")


class _FakeSourceControl:
    def __init__(self) -> None:
        self.created: list[str] = []

    async def create_project(self, name: str, description: str | None = None) -> ExternalReference:
        self.created.append(name)
        return ExternalReference(
            provider="gitlab", external_id="gl-1", external_type="project", namespace="group/repo"
        )


class _FakeDocumentation:
    def __init__(self) -> None:
        self.created: list[str] = []

    async def create_space(self, name: str) -> ExternalReference:
        self.created.append(name)
        return ExternalReference(provider="xwiki", external_id=name, external_type="space")


async def _service(
    *,
    wm: object | None = None,
    sc: object | None = None,
    doc: object | None = None,
) -> tuple[ProjectProvisioningService, InMemoryProjectRepository]:
    projects = InMemoryProjectRepository()
    service = ProjectProvisioningService(
        projects=projects,
        work_management=wm,  # type: ignore[arg-type]
        source_control=sc,  # type: ignore[arg-type]
        documentation=doc,  # type: ignore[arg-type]
        bootstrap=None,
        event_bus=InMemoryEventBus(),
    )
    return service, projects


async def test_gate_create_canonical_only() -> None:
    service, projects = await _service()
    project = await service.create_canonical("Brain only")
    stored = await projects.get(project.id)
    assert stored is not None
    assert stored.name == "Brain only"
    assert stored.external_refs == []


async def test_gate_create_connected_provisions_all_providers() -> None:
    wm = _FakeWorkManagement()
    sc = _FakeSourceControl()
    doc = _FakeDocumentation()
    service, _ = await _service(wm=wm, sc=sc, doc=doc)

    result = await service.create_connected("ADAS Platform", "platform docs")
    assert result.project.external_refs is not None
    refs = result.refs_added
    assert {r.provider for r in refs} == {"openproject", "gitlab", "xwiki"}
    assert wm.created == ["ADAS Platform"]
    assert sc.created == ["ADAS Platform"]
    assert doc.created == ["ADASPlatform"]
    # Refs persisted on the canonical project.
    assert {r.provider for r in result.project.external_refs} == {
        "openproject",
        "gitlab",
        "xwiki",
    }


async def test_gate_provision_skips_unconfigured_providers() -> None:
    service, _ = await _service()  # nothing configured
    project = await service.create_canonical("lonely")
    result = await service.provision(project.id)
    assert result.refs_added == []
    assert result.project.external_refs == []
    notes = " ".join(result.details)
    assert "work management: not configured, skipped" in notes
    assert "source control: not configured, skipped" in notes
    assert "documentation: not configured, skipped" in notes


async def test_gate_provision_failure_isolates_providers() -> None:
    wm = _FakeWorkManagement(fail=True)
    sc = _FakeSourceControl()
    service, _ = await _service(wm=wm, sc=sc)
    project = await service.create_canonical("partial")
    result = await service.provision(project.id)
    # The failing provider did not block the others.
    assert {r.provider for r in result.refs_added} == {"gitlab"}
    assert any("provisioning failed" in d for d in result.details)
    assert any("source control: created" in d for d in result.details)
    assert {r.provider for r in result.project.external_refs} == {"gitlab"}


async def test_gate_provision_unsupported_provider_reported() -> None:
    wm = _FakeWorkManagement(unsupported=True)
    service, _ = await _service(wm=wm)
    project = await service.create_canonical("jira-only")
    result = await service.provision(project.id)
    assert result.refs_added == []
    assert any("not supported" in d for d in result.details)


async def test_gate_bootstrap_links_existing_externals() -> None:
    service, _ = await _service()
    project = await service.create_canonical("connect-me")
    result = await service.bootstrap(
        project.id,
        ExternalProjects(
            work_management="42",
            source_control="group/adas-platform",
            documentation="ADASPlatform",
        ),
    )
    assert {r.provider for r in result.refs_added} == {"openproject", "gitlab", "xwiki"}
    stored_refs = {r.provider: r.external_id for r in result.project.external_refs}
    assert stored_refs["openproject"] == "42"
    assert stored_refs["gitlab"] == "group/adas-platform"
    assert stored_refs["xwiki"] == "ADASPlatform"
    assert "linked existing" in " ".join(result.details)


async def test_gate_bootstrap_is_idempotent() -> None:
    service, projects = await _service()
    project = await service.create_canonical("twice")
    external = ExternalProjects(work_management="42")
    first = await service.bootstrap(project.id, external)
    assert len(first.refs_added) == 1
    second = await service.bootstrap(project.id, external)
    assert second.refs_added == []
    assert any("already linked" in d for d in second.details)
    stored = await projects.get(project.id)
    assert stored is not None
    assert len(stored.external_refs) == 1


async def test_gate_bootstrap_missing_project_raises() -> None:
    service, _ = await _service()
    try:
        await service.bootstrap(ProjectId(uuid.uuid4()), ExternalProjects())
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
