from __future__ import annotations

import importlib
from pathlib import Path


CORE_MODULES = [
    "agent_core.main",
    "agent_core.models",
    "agent_core.schemas",
    "agent_core.api.events",
    "agent_core.api.agents",
    "agent_core.application.project_orchestrator",
    "agent_core.skills",
    "agent_core.skills.context_capsule",
    "agent_core.skills.implementation_status_classification",
    "agent_core.skills.neo4j_projection",
    "agent_core.skills.openproject_projection",
    "agent_core.skills.plan_validation",
    "agent_core.skills.repository_inspection",
    "agent_core.skills.requirement_extraction",
    "agent_core.skills.weaviate_projection",
    "agent_core.workflow.graph",
    "agent_core.workflow.persistence_setup",
    "agent_core.workflow.runner",
    "agent_core.workflow.state",
    "agent_core.ports.executions",
    "agent_core.persistence.executions",
    "agent_core.adapters.command_runner",
    "agent_core.adapters.lsp",
    "agent_core.adapters.neo4j_store",
    "agent_core.adapters.repository_analysis",
    "agent_core.adapters.repository_filesystem",
    "agent_core.adapters.tree_sitter_analysis",
    "agent_core.adapters.weaviate_store",
    "agent_core.api.repositories",
    "agent_core.domain.code_analysis",
    "agent_core.domain.coding",
    "agent_core.domain.repositories",
    "agent_core.ports.coding_attempts",
    "agent_core.ports.repository_analysis",
    "agent_core.persistence.coding_attempts",
    "agent_core.persistence.agent_platform",
    "agent_core.persistence.agent_flows",
    "agent_core.services.coding_service",
    "agent_core.services.agent_platform_service",
    "agent_core.services.agent_execution_codec",
    "agent_core.services.agent_platform_composition",
    "agent_core.services.repository_analysis_service",
    "agent_core.services.repository_projection_service",
    "agent_core.services.repository_write_tracker",
    "agent_core.agent_platform",
    "agent_core.agent_platform.adapters",
    "agent_core.agent_platform.agents.base",
    "agent_core.agent_platform.agents.planning",
    "agent_core.agent_platform.agents.coding",
    "agent_core.agent_platform.agents.verification",
    "agent_core.agent_platform.config",
    "agent_core.agent_platform.factory",
    "agent_core.agent_platform.orchestration",
    "agent_core.agent_platform.runtime",
    "agent_core.workers.agent_flow_worker",
]


def test_planning_agent_core_modules_import(monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(repo_root / "agent_core"))

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://coding_agent:change-me@localhost:5432/coding_agent",
    )
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("LLM_MODEL", "local-coding-model")
    monkeypatch.setenv("LLM_API_KEY", "local-not-secret")
    monkeypatch.setenv("OPENPROJECT_BASE_URL", "http://localhost:8081")
    monkeypatch.setenv("OPENPROJECT_API_KEY", "placeholder-key")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "change-me")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")

    for module_name in CORE_MODULES:
        importlib.import_module(module_name)
