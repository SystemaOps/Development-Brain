from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

import pytest

from agent_core.workflow.persistence_setup import initialize_langgraph_persistence


class FakePersistenceContext:
    def __init__(self, calls: list[tuple[str, str]], kind: str, database_uri: str):
        self.calls = calls
        self.kind = kind
        self.database_uri = database_uri

    async def __aenter__(self):
        self.calls.append((f"{self.kind}.enter", self.database_uri))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.calls.append((f"{self.kind}.exit", self.database_uri))

    async def setup(self) -> None:
        self.calls.append((f"{self.kind}.setup", self.database_uri))


def make_fake_persistence_class(kind: str, calls: list[tuple[str, str]]):
    class FakePersistenceClass:
        @classmethod
        def from_conn_string(cls, database_uri: str):
            calls.append((f"{kind}.from_conn_string", database_uri))
            return FakePersistenceContext(calls, kind, database_uri)

    return FakePersistenceClass


@pytest.mark.asyncio
async def test_initialize_langgraph_persistence_sets_up_checkpointer_and_store():
    calls: list[tuple[str, str]] = []
    database_uri = "postgresql://user:pass@localhost:5432/app"

    result = await initialize_langgraph_persistence(
        database_uri,
        saver_cls=make_fake_persistence_class("saver", calls),
        store_cls=make_fake_persistence_class("store", calls),
    )

    assert result.database_uri == database_uri
    assert result.checkpointer_setup is True
    assert result.store_setup is True
    assert calls == [
        ("saver.from_conn_string", database_uri),
        ("saver.enter", database_uri),
        ("saver.setup", database_uri),
        ("saver.exit", database_uri),
        ("store.from_conn_string", database_uri),
        ("store.enter", database_uri),
        ("store.setup", database_uri),
        ("store.exit", database_uri),
    ]


@pytest.mark.asyncio
async def test_initialize_langgraph_persistence_can_skip_store_setup():
    calls: list[tuple[str, str]] = []
    database_uri = "postgresql://user:pass@localhost:5432/app"

    result = await initialize_langgraph_persistence(
        database_uri,
        include_store=False,
        saver_cls=make_fake_persistence_class("saver", calls),
        store_cls=make_fake_persistence_class("store", calls),
    )

    assert result.checkpointer_setup is True
    assert result.store_setup is False
    assert calls == [
        ("saver.from_conn_string", database_uri),
        ("saver.enter", database_uri),
        ("saver.setup", database_uri),
        ("saver.exit", database_uri),
    ]


@pytest.mark.asyncio
async def test_planning_workflow_runner_uses_stable_resume_config(monkeypatch):
    from agent_core.workflow import runner as runner_module

    captured = {}

    class FakeGraph:
        async def ainvoke(self, state, config):
            captured["state"] = state
            captured["config"] = config
            return {"status": "ok"}

    def fake_build_planning_graph(db, checkpointer, store):
        captured["build_args"] = {
            "db": db,
            "checkpointer": checkpointer,
            "store": store,
        }
        return FakeGraph()

    monkeypatch.setattr(runner_module, "build_planning_graph", fake_build_planning_graph)

    db = object()
    checkpointer = object()
    store = object()
    session_id = uuid4()

    result = await runner_module.PlanningWorkflowRunner(
        db=db,
        checkpointer=checkpointer,
        store=store,
    ).run(session_id)

    assert result == {"status": "ok"}
    assert captured["build_args"] == {
        "db": db,
        "checkpointer": checkpointer,
        "store": store,
    }
    assert captured["state"] == {"session_id": session_id, "errors": []}
    assert captured["config"] == {
        "configurable": {
            "thread_id": f"planning-session-{session_id}",
        }
    }


def test_setup_langgraph_script_env_loading_and_uri_helpers(tmp_path, monkeypatch):
    script = _load_setup_script_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/app",
                "EXISTING=replace-me",
                "QUOTED='quoted-value'",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EXISTING", "keep-me")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)

    loaded = script.load_env_file(env_file)

    assert loaded == 2
    assert script.normalize_database_uri(
        "postgresql+asyncpg://user:pass@localhost:5432/app"
    ) == "postgresql://user:pass@localhost:5432/app"
    assert script.redact_database_uri(
        "postgresql://user:pass@localhost:5432/app?sslmode=disable"
    ) == "postgresql://user:***@localhost:5432/app?sslmode=disable"
    assert script.os.environ["DATABASE_URL"] == (
        "postgresql+asyncpg://user:pass@localhost:5432/app"
    )
    assert script.os.environ["EXISTING"] == "keep-me"
    assert script.os.environ["QUOTED"] == "quoted-value"


@pytest.mark.asyncio
async def test_langgraph_postgres_checkpoint_survives_recreated_checkpointer():
    database_uri = os.getenv("LANGGRAPH_PERSISTENCE_TEST_DATABASE_URL")
    if not database_uri:
        pytest.skip("Set LANGGRAPH_PERSISTENCE_TEST_DATABASE_URL to run with real Postgres")

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.graph import END, START, StateGraph

    class ResumeState(TypedDict, total=False):
        values: list[str]

    async def append_value(state: ResumeState) -> ResumeState:
        return {"values": [*state.get("values", []), "persisted"]}

    def build_graph(checkpointer):
        graph = StateGraph(ResumeState)
        graph.add_node("append_value", append_value)
        graph.add_edge(START, "append_value")
        graph.add_edge("append_value", END)
        return graph.compile(checkpointer=checkpointer)

    config = {
        "configurable": {
            "thread_id": f"restart-test-{uuid4()}",
        }
    }

    async with AsyncPostgresSaver.from_conn_string(database_uri) as first_checkpointer:
        await first_checkpointer.setup()
        first_graph = build_graph(first_checkpointer)
        first_result = await first_graph.ainvoke({"values": []}, config=config)

    async with AsyncPostgresSaver.from_conn_string(database_uri) as second_checkpointer:
        second_graph = build_graph(second_checkpointer)
        restored_state = await second_graph.aget_state(config)

    assert first_result == {"values": ["persisted"]}
    assert restored_state.values["values"] == ["persisted"]


def _load_setup_script_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "infra" / "scripts" / "setup_langgraph_persistence.py"
    )
    spec = importlib.util.spec_from_file_location("setup_langgraph_persistence", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module
