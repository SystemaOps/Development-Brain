"""Phase 22 golden tests and completion gate.

The runtime can explain which capabilities are usable (Task 22.1), refresh
health via probes (Task 22.4), and evaluate readiness from required vs
optional capabilities (Task 22.3) — without inferring availability from
exceptions during normal workflows.
"""

from __future__ import annotations

import uuid

from brain.bootstrap.capabilities import CapabilityRegistry
from brain.bootstrap.container import create_brain_container
from brain.bootstrap.settings import (
    BrainSettings,
    DocumentationSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)
from brain.domain.capabilities import (
    CapabilityDescriptor,
    CapabilityHealth,
    CapabilityName,
    CapabilityStatus,
)
from brain.ports.capabilities import CapabilityRegistry as CapabilityRegistryPort


def _settings() -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
        storage_semantic=WeaviateSettings(host="localhost"),
        storage_queue=RedisSettings(url="redis://localhost:6379/0"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
    )


def test_capability_models() -> None:
    assert CapabilityStatus.AVAILABLE.value == "AVAILABLE"
    assert CapabilityStatus.DEGRADED.value == "DEGRADED"
    assert CapabilityStatus.DISABLED.value == "DISABLED"
    assert CapabilityStatus.UNAVAILABLE.value == "UNAVAILABLE"
    assert CapabilityStatus.MISCONFIGURED.value == "MISCONFIGURED"

    health = CapabilityHealth(status=CapabilityStatus.AVAILABLE, detail="ok")
    assert health.is_usable
    assert CapabilityHealth(status=CapabilityStatus.DISABLED).is_usable is False

    descriptor = CapabilityDescriptor(
        name=CapabilityName.POSTGRES, provider="postgres", required=True, health=health
    )
    assert descriptor.status == CapabilityStatus.AVAILABLE


async def test_registry_conforms_to_port() -> None:
    registry = CapabilityRegistry()
    assert isinstance(registry, CapabilityRegistryPort)


async def test_registry_snapshot_and_status() -> None:
    registry = CapabilityRegistry()
    registry.register_health(
        CapabilityName.POSTGRES,
        provider="postgres",
        required=True,
        status=CapabilityStatus.AVAILABLE,
    )
    registry.register_health(
        CapabilityName.DOCUMENTATION_XWIKI,
        required=False,
        status=CapabilityStatus.DISABLED,
    )
    snapshot = registry.snapshot()
    assert snapshot["postgres"].status == CapabilityStatus.AVAILABLE
    assert snapshot["documentation_xwiki"].status == CapabilityStatus.DISABLED
    assert registry.is_ready() is True


async def test_required_unavailable_blocks_readiness() -> None:
    registry = CapabilityRegistry()
    registry.register_health(
        CapabilityName.POSTGRES,
        provider="postgres",
        required=True,
        status=CapabilityStatus.UNAVAILABLE,
        detail="cannot connect",
    )
    assert registry.is_ready() is False
    assert "postgres" in registry.ready_problems()[0]


async def test_optional_unavailable_does_not_block_readiness() -> None:
    registry = CapabilityRegistry()
    registry.register_health(
        CapabilityName.POSTGRES,
        provider="postgres",
        required=True,
        status=CapabilityStatus.AVAILABLE,
    )
    registry.register_health(
        CapabilityName.WORK_MANAGEMENT,
        required=False,
        status=CapabilityStatus.UNAVAILABLE,
    )
    assert registry.is_ready() is True
    assert registry.ready_problems() == []


async def test_refresh_runs_probes_and_updates_status() -> None:
    registry = CapabilityRegistry()
    registry.register_health(
        CapabilityName.POSTGRES,
        provider="postgres",
        required=True,
        status=CapabilityStatus.UNAVAILABLE,
        probe=lambda: CapabilityHealth(status=CapabilityStatus.AVAILABLE, detail="ok"),
    )
    postgres = registry.get(CapabilityName.POSTGRES)
    assert postgres is not None
    assert postgres.status == CapabilityStatus.UNAVAILABLE
    await registry.refresh()
    postgres = registry.get(CapabilityName.POSTGRES)
    assert postgres is not None
    assert postgres.status == CapabilityStatus.AVAILABLE


async def test_refresh_async_probe_and_failure() -> None:
    registry = CapabilityRegistry()

    async def _ok() -> CapabilityHealth:
        return CapabilityHealth(status=CapabilityStatus.AVAILABLE)

    def _fail() -> bool:
        raise ConnectionError("down")

    registry.register_health(CapabilityName.REDIS, probe=_ok, status=CapabilityStatus.UNAVAILABLE)
    registry.register_health(
        CapabilityName.WEAVIATE, probe=_fail, status=CapabilityStatus.AVAILABLE
    )
    await registry.refresh()
    redis_desc = registry.get(CapabilityName.REDIS)
    weaviate_desc = registry.get(CapabilityName.WEAVIATE)
    assert redis_desc is not None
    assert weaviate_desc is not None
    assert redis_desc.status == CapabilityStatus.AVAILABLE
    assert weaviate_desc.status == CapabilityStatus.UNAVAILABLE


async def test_gate_core_healthy_readiness() -> None:
    container = await create_brain_container(_settings())
    assert container.is_ready() is True
    assert container.ready_problems() == []
    caps = container.capabilities()
    assert caps["postgres"] == "AVAILABLE"
    assert caps["neo4j"] == "AVAILABLE"
    assert caps["weaviate"] == "AVAILABLE"
    assert caps["redis"] == "AVAILABLE"
    await container.close()


async def test_gate_optional_provider_unavailable_still_ready() -> None:
    settings = _settings()
    settings.work_management = WorkManagementSettings(
        enabled=True,
        provider="openproject",
        required=False,
        base_url="http://127.0.0.1:1",
        api_key="key",
        project_id=str(uuid.uuid4()),
    )
    container = await create_brain_container(settings)
    assert container.capabilities()["work_management"] == "UNAVAILABLE"
    assert container.is_ready() is True
    await container.close()


async def test_gate_disabled_xwiki_still_ready() -> None:
    settings = _settings()
    settings.documentation = DocumentationSettings(git_enabled=False, xwiki_enabled=False)
    container = await create_brain_container(settings)
    assert container.capabilities()["documentation_xwiki"] == "DISABLED"
    assert container.is_ready() is True
    await container.close()


async def test_gate_misconfigured_provider_reported() -> None:
    settings = _settings()
    settings.work_management = WorkManagementSettings(
        enabled=True, provider="openproject", required=False, base_url=""
    )
    container = await create_brain_container(settings)
    assert container.capabilities()["work_management"] == "MISCONFIGURED"
    await container.close()


async def test_gate_refresh_rechecks_postgres() -> None:
    container = await create_brain_container(_settings())
    assert container.capabilities()["postgres"] == "AVAILABLE"
    await container.capability_registry().refresh()
    assert container.capabilities()["postgres"] in {"AVAILABLE", "UNAVAILABLE"}
    await container.close()
