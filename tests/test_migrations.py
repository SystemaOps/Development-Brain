"""Migration tests (Task 2.6).

Verify the classic lifecycle against a dedicated database:

    empty DB -> alembic upgrade head -> schema valid
    downgrade base -> schema gone
    upgrade head again -> schema valid (idempotent re-upgrade)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from tests.conftest import MIGRATION_TEST_DATABASE_URL, postgres_reachable

EXPECTED_TABLES = {
    "actors",
    "artifacts",
    "code_files",
    "code_relations",
    "code_symbols",
    "context_capsules",
    "decisions",
    "document_nodes",
    "document_versions",
    "documents",
    "evidence",
    "executions",
    "external_references",
    "interfaces",
    "plans",
    "projects",
    "repositories",
    "repository_change_sets",
    "repository_snapshots",
    "requirements",
    "resources",
    "software_components",
    "software_domains",
    "systems",
    "topology_claims",
    "topology_dependencies",
    "verification_results",
    "verification_runs",
    "work_items",
    "work_management_mappings",
    "sync_conflicts",
    "workflow_checkpoints",
    "approvals",
}

pytestmark = pytest.mark.skipif(
    not postgres_reachable(MIGRATION_TEST_DATABASE_URL),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


def _alembic_config(url: str) -> Config:
    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _table_names(url: str) -> set[str]:
    async def _run() -> set[str]:
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
        await engine.dispose()
        return names

    return asyncio.run(_run())


def test_upgrade_head_creates_full_schema() -> None:
    command.upgrade(_alembic_config(MIGRATION_TEST_DATABASE_URL), "head")
    tables = _table_names(MIGRATION_TEST_DATABASE_URL)
    assert tables >= EXPECTED_TABLES, f"missing tables: {EXPECTED_TABLES - tables}"
    assert "alembic_version" in tables


def test_downgrade_base_drops_schema() -> None:
    command.downgrade(_alembic_config(MIGRATION_TEST_DATABASE_URL), "base")
    tables = _table_names(MIGRATION_TEST_DATABASE_URL)
    assert not (EXPECTED_TABLES & tables), f"tables still present: {EXPECTED_TABLES & tables}"


def test_upgrade_after_downgrade_restores_schema() -> None:
    cfg = _alembic_config(MIGRATION_TEST_DATABASE_URL)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    tables = _table_names(MIGRATION_TEST_DATABASE_URL)
    assert tables >= EXPECTED_TABLES
