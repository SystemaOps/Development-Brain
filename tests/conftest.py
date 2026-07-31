from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


def pytest_configure() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    repo_root = Path(__file__).resolve().parents[1]
    package_root = repo_root / "agent_core"
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://coding_agent:change-me@localhost:5432/coding_agent",
    )
    os.environ.setdefault("LLM_BASE_URL", "http://localhost:8080/v1")
    os.environ.setdefault("LLM_MODEL", "local-coding-model")
    os.environ.setdefault("LLM_API_KEY", "local-not-secret")
    os.environ.setdefault("OPENPROJECT_BASE_URL", "http://localhost:8081")
    os.environ.setdefault("OPENPROJECT_API_KEY", "placeholder-key")
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "change-me")
    os.environ.setdefault("NEO4J_DATABASE", "neo4j")
