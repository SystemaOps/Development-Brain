from __future__ import annotations

import ast
from pathlib import Path


FORBIDDEN_BOUNDARY_IMPORTS = {
    "fastapi",
    "sqlalchemy",
    "neo4j",
    "weaviate",
    "redis",
    "httpx",
    "langgraph",
    "psycopg",
}


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_domain_and_ports_do_not_import_vendor_adapters():
    repo_root = Path(__file__).resolve().parents[1]
    package_root = repo_root / "agent_core" / "agent_core"
    checked_files = [
        *sorted((package_root / "domain").glob("*.py")),
        *sorted((package_root / "ports").glob("*.py")),
    ]

    assert checked_files

    violations = {
        str(path.relative_to(repo_root)): sorted(_import_roots(path) & FORBIDDEN_BOUNDARY_IMPORTS)
        for path in checked_files
        if _import_roots(path) & FORBIDDEN_BOUNDARY_IMPORTS
    }

    assert violations == {}


def test_settings_accept_current_and_target_environment_names(monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(repo_root / "agent_core"))

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CHECKPOINT_DATABASE_URL", raising=False)
    monkeypatch.delenv("OPENPROJECT_API_KEY", raising=False)
    monkeypatch.delenv("NEO4J_USER", raising=False)

    monkeypatch.setenv("POSTGRES_DSN", "postgresql+asyncpg://user:pass@localhost:5432/app")
    monkeypatch.setenv("LANGGRAPH_POSTGRES_DSN", "postgresql://user:pass@localhost:5432/app")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("LLM_MODEL", "local-coding-model")
    monkeypatch.setenv("OPENPROJECT_BASE_URL", "http://localhost:8081")
    monkeypatch.setenv("OPENPROJECT_API_TOKEN", "token-from-target-name")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j-target")
    monkeypatch.setenv("NEO4J_PASSWORD", "change-me")

    from agent_core.config.settings import Settings

    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://user:pass@localhost:5432/app"
    assert settings.checkpoint_database_url == "postgresql://user:pass@localhost:5432/app"
    assert settings.openproject_api_key == "token-from-target-name"
    assert settings.neo4j_username == "neo4j-target"
    assert settings.neo4j_user == "neo4j-target"
