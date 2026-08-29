"""Phase 36 golden tests and completion gate.

Backstage provides higher-confidence declared topology when available, but the
Brain remains fully capable of deriving topology itself: the adapter maps
declared entities to canonical software-model, reconciliation preserves
conflicts (never overwrites), conflict observations are created, and the
disabled mode keeps the derived catalog + Brain ready.
"""

from __future__ import annotations

import pytest

from brain.adapters.catalog.backstage import BackstageCatalogAdapter
from brain.application.backstage_reconciliation import (
    BackstageReconciliationService,
)
from brain.application.observations import ObservationService
from brain.bootstrap.container import (
    BrainContainer,
    create_brain_container,
)
from brain.bootstrap.settings import (
    BrainSettings,
    DocumentationSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    SoftwareCatalogSettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)
from brain.domain.projects import Project
from brain.domain.software_model import (
    ComponentType,
    SoftwareComponent,
)
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


def _settings(catalog: SoftwareCatalogSettings | None = None) -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
        storage_semantic=WeaviateSettings(host="localhost"),
        storage_queue=RedisSettings(url="redis://localhost:6379/0"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        software_catalog=catalog or SoftwareCatalogSettings(provider="derived"),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
    )


def _observations(container: BrainContainer) -> ObservationService:
    service = container.services["observations"]
    assert isinstance(service, ObservationService)
    return service


class _FakeBackstageTransport:
    """Implements the BackstageTransport surface with canned data."""

    def __init__(
        self,
        components: list[dict[str, object]] | None = None,
        resources: list[dict[str, object]] | None = None,
        systems: list[dict[str, object]] | None = None,
        domains: list[dict[str, object]] | None = None,
    ) -> None:
        self._entities = {
            "Component": components or [],
            "Resource": resources or [],
            "System": systems or [],
            "Domain": domains or [],
        }

    async def list_entities(self, kind: str) -> list[dict[str, object]]:
        return list(self._entities.get(kind, []))

    async def list_dependencies(self) -> list[tuple[str, str]]:
        return [("payment-service", "ledger-service")]


async def test_adapter_maps_domains_systems_and_components() -> None:
    """Declared entities map to canonical software-model (36.2)."""
    transport = _FakeBackstageTransport(
        components=[
            {
                "metadata": {"name": "auth-service"},
                "spec": {"type": "service", "lifecycle": "production"},
            },
            {
                "metadata": {"name": "web-ui"},
                "spec": {"type": "website"},
            },
        ],
        resources=[{"metadata": {"name": "users-db"}, "spec": {"type": "database"}}],
        systems=[{"metadata": {"name": "auth-system"}}],
        domains=[{"metadata": {"name": "identity"}}],
    )
    adapter = BackstageCatalogAdapter(transport=transport)
    project = Project(name="p")
    components = await adapter.list_components(project)
    assert {c.name for c in components} == {"auth-service", "web-ui"}
    assert next(c for c in components if c.name == "auth-service").component_type == (
        ComponentType.BACKEND_SERVICE
    )
    assert next(c for c in components if c.name == "web-ui").component_type == (
        ComponentType.FRONTEND_APPLICATION
    )
    resources = await adapter.list_resources(project)
    assert resources[0].name == "users-db"
    systems = await adapter.list_systems(project)
    assert systems[0].name == "auth-system"
    domains = await adapter.list_domains(project)
    assert domains[0].name == "identity"


async def test_reconciliation_preserves_conflicts_without_overwrite() -> None:
    """Declared vs discovered disagreement is preserved, not overwritten (36.3)."""
    container = await create_brain_container(_settings())
    try:
        project = Project(name="recon")
        await container.repositories.projects.create(project)

        # Discovered: payment-service as a library.
        discovered = SoftwareComponent(
            project_id=project.id,
            name="payment-service",
            component_type=ComponentType.LIBRARY,
        )
        await container.repositories.software_catalog.upsert_component(discovered)

        transport = _FakeBackstageTransport(
            components=[
                {
                    "metadata": {"name": "payment-service"},
                    "spec": {"type": "service"},
                },
                {
                    "metadata": {"name": "ghost-service"},
                    "spec": {"type": "service"},
                },
            ]
        )
        service = BackstageReconciliationService(
            backstage=BackstageCatalogAdapter(transport=transport),
            container=container,
            observations=_observations(container),
        )
        result = await service.reconcile(project)
        assert result.checked_components == 2
        assert any("type differs" in c for c in result.conflicts)
        assert any("declared in Backstage but not discovered" in c for c in result.conflicts)
        # The discovered component type was NOT overwritten.
        stored = await container.repositories.software_catalog.list_components(project.id)
        assert stored[0].component_type == ComponentType.LIBRARY
        # Conflict observations were created.
        assert result.observations_created
        observations = await container.repositories.observations.list_by_project(project.id)
        assert observations
    finally:
        await container.close()


async def test_reconciliation_agreement_updates_lifecycle_only() -> None:
    """Matching types update lifecycle without conflict observations."""
    container = await create_brain_container(_settings())
    try:
        project = Project(name="recon-ok")
        await container.repositories.projects.create(project)
        discovered = SoftwareComponent(
            project_id=project.id,
            name="auth-service",
            component_type=ComponentType.BACKEND_SERVICE,
        )
        await container.repositories.software_catalog.upsert_component(discovered)

        transport = _FakeBackstageTransport(
            components=[
                {
                    "metadata": {"name": "auth-service"},
                    "spec": {"type": "service", "lifecycle": "production"},
                }
            ]
        )
        service = BackstageReconciliationService(
            backstage=BackstageCatalogAdapter(transport=transport),
            container=container,
            observations=_observations(container),
        )
        result = await service.reconcile(project)
        assert result.conflicts == []
        stored = await container.repositories.software_catalog.list_components(project.id)
        assert stored[0].lifecycle == "production"
        assert stored[0].component_type == ComponentType.BACKEND_SERVICE
    finally:
        await container.close()


async def test_reconciliation_no_backstage_noop() -> None:
    """With no Backstage the reconciliation safely no-ops (36.5)."""
    container = await create_brain_container(_settings())
    try:
        project = Project(name="recon-none")
        await container.repositories.projects.create(project)
        service = BackstageReconciliationService(
            backstage=None,
            container=container,
            observations=_observations(container),
        )
        result = await service.reconcile(project)
        assert result.checked_components == 0
        assert result.conflicts == []
    finally:
        await container.close()


async def test_gate_disabled_mode_keeps_derived_catalog_and_brain_ready() -> None:
    """Backstage disabled -> DerivedSoftwareCatalog available -> Brain ready."""
    container = await create_brain_container(
        _settings(SoftwareCatalogSettings(provider="derived", external_enabled=False))
    )
    try:
        assert container.capabilities()["software_catalog"] == "AVAILABLE"
        assert container.is_ready() is True
        assert container.software_catalog is not None
        # No backstage reconciliation service is active (null backstage).
        service = container.services["backstage_reconciliation"]
        assert isinstance(service, BackstageReconciliationService)
        project = Project(name="disabled")
        result = await service.reconcile(project)
        assert result.checked_components == 0
    finally:
        await container.close()


async def test_gate_backstage_configured_reports_available() -> None:
    """With Backstage configured the capability is AVAILABLE."""
    container = await create_brain_container(
        _settings(
            SoftwareCatalogSettings(
                provider="backstage",
                external_enabled=True,
                external_url="http://backstage:7007",
            )
        )
    )
    try:
        assert container.capabilities()["software_catalog"] == "AVAILABLE"
        assert container.is_ready() is True
        from brain.adapters.catalog.backstage import BackstageCatalogAdapter

        assert isinstance(container.software_catalog, BackstageCatalogAdapter)
    finally:
        await container.close()
