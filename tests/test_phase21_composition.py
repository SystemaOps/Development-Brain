"""Phase 21 golden tests and completion gate.

One composition root can construct and close the complete Brain runtime
without any API or CLI.  Core-only composition succeeds with all optional
integrations disabled; an optional provider that is enabled but unreachable
yields ``UNAVAILABLE`` instead of failing container construction.
"""

from __future__ import annotations

import uuid

from brain.bootstrap.container import BrainContainer, create_brain_container
from brain.bootstrap.settings import (
    ArtifactStoreSettings,
    AutomationPolicySettings,
    BrainSettings,
    DocumentationSettings,
    DocumentConversionSettings,
    ExecutorSettings,
    HumanApprovalSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    SoftwareCatalogSettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)


def _core_only_settings() -> BrainSettings:
    """Postgres/Neo4j/Weaviate/Redis enabled; all integrations disabled."""
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
        storage_semantic=WeaviateSettings(host="localhost"),
        storage_queue=RedisSettings(url="redis://localhost:6379/0"),
        storage_artifacts=ArtifactStoreSettings(provider="local"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        document_conversion=DocumentConversionSettings(enabled=False),
        software_catalog=SoftwareCatalogSettings(provider="derived", external_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        executors=ExecutorSettings(coding_provider="fake"),
        verification=VerificationSettings(require_pass_before_pr=True),
        automation=AutomationPolicySettings(auto_create_pr=False),
        human_approval=HumanApprovalSettings(),
    )


async def test_gate_core_only_composition_constructs_and_closes() -> None:
    container = await create_brain_container(_core_only_settings())
    assert isinstance(container, BrainContainer)

    # Core capability states.
    caps = container.capabilities()
    assert caps["postgres"] == "AVAILABLE"
    assert caps["neo4j"] == "AVAILABLE"
    assert caps["weaviate"] == "AVAILABLE"
    assert caps["redis"] == "AVAILABLE"

    # Optional integrations are disabled / null.
    assert caps["work_management"] == "DISABLED"
    assert container.work_management is None
    assert caps["software_catalog"] == "AVAILABLE"
    assert caps["documentation_xwiki"] == "DISABLED"
    assert caps["source_control"] == "DISABLED"
    assert container.documentation_ports == []
    # Document conversion exists as a null-converter service: native ingestion
    # works, conversion capability is DISABLED.
    assert caps["document_conversion"] == "DISABLED"
    assert container.document_conversion is not None
    assert container.document_conversion.converter is None

    # Core application services are present.
    for key in (
        "context_engine",
        "planning",
        "verification",
        "workflow",
        "code_intelligence",
        "jit_retrieval",
        "document_ingestion",
        "topology_discovery",
        "semantic_indexing",
        "graph_projection",
        "observability",
        "policy",
        "model_router",
    ):
        assert key in container.services, f"missing service {key}"
    assert container.services["context_engine"] is not None
    assert container.services["planning"] is not None
    assert container.services["verification"] is not None
    assert container.services["workflow"] is not None

    # Milestone-1 default executor is registered.
    assert [d.name for d in container.executor_descriptors] == ["fake"]

    await container.close()


async def test_gate_close_is_idempotent() -> None:
    container = await create_brain_container(_core_only_settings())
    await container.close()
    await container.close()  # must not raise


async def test_gate_optional_provider_unreachable_does_not_fail_container() -> None:
    settings = _core_only_settings()
    settings.work_management = WorkManagementSettings(
        enabled=True,
        provider="openproject",
        required=False,
        base_url="http://127.0.0.1:1",
        api_key="key",
        project_id=str(uuid.uuid4()),
    )
    container = await create_brain_container(settings)
    assert container.work_management is None
    assert container.capabilities()["work_management"] == "UNAVAILABLE"
    # The Brain remains usable.
    assert container.services["context_engine"] is not None
    assert container.services["planning"] is not None
    await container.close()


async def test_gate_optional_provider_disabled_reports_disabled() -> None:
    settings = _core_only_settings()
    settings.work_management = WorkManagementSettings(enabled=False, provider="openproject")
    container = await create_brain_container(settings)
    assert container.capabilities()["work_management"] == "DISABLED"
    await container.close()


async def test_gate_misconfigured_provider_reports_misconfigured() -> None:
    settings = _core_only_settings()
    settings.work_management = WorkManagementSettings(
        enabled=True, provider="openproject", required=False, base_url=""
    )
    container = await create_brain_container(settings)
    assert container.capabilities()["work_management"] == "MISCONFIGURED"
    await container.close()
