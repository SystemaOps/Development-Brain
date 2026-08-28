"""Bounded workflows: ingestion, planning, verification (Phase 28).

Each is a small LangGraph StateGraph; orchestrators remain bounded rather than
one huge graph (AGENT_2.md §33).
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from brain.bootstrap.container import BrainContainer
from brain.orchestration.engineering_workflow import build_engineering_workflow


class SimpleState(TypedDict):
    entity_id: str
    status: str
    error: str | None


class IngestionWorkflowBuilder:
    """Stages: fetch source -> identify revision -> parse -> normalize ->
    extract knowledge -> update graph -> update semantic index -> mark current
    (Task 28.4)."""

    def __init__(self, container: BrainContainer) -> None:
        self._container = container

    async def _fetch(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "fetch"}

    async def _revision(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "revision"}

    async def _parse(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "parse"}

    async def _normalize(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "normalize"}

    async def _extract(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "extract"}

    async def _graph(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "graph"}

    async def _index(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "index"}

    async def _current(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "current"}

    def build(self) -> StateGraph[SimpleState]:
        graph: StateGraph[SimpleState] = StateGraph(SimpleState)
        graph.add_node("fetch", self._fetch)
        graph.add_node("revision", self._revision)
        graph.add_node("parse", self._parse)
        graph.add_node("normalize", self._normalize)
        graph.add_node("extract", self._extract)
        graph.add_node("graph", self._graph)
        graph.add_node("index", self._index)
        graph.add_node("current", self._current)
        graph.add_edge(START, "fetch")
        graph.add_edge("fetch", "revision")
        graph.add_edge("revision", "parse")
        graph.add_edge("parse", "normalize")
        graph.add_edge("normalize", "extract")
        graph.add_edge("extract", "graph")
        graph.add_edge("graph", "index")
        graph.add_edge("index", "current")
        graph.add_edge("current", END)
        return graph


class PlanningWorkflowBuilder:
    """Stages: collect requirements -> assess ambiguity -> inspect current
    implementation -> decompose work -> validate plan -> sync/publish WorkItems
    (Task 28.5)."""

    def __init__(self, container: BrainContainer) -> None:
        self._container = container

    async def _collect(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "collect"}

    async def _assess(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "assess"}

    async def _inspect(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "inspect"}

    async def _decompose(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "decompose"}

    async def _validate(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "validate"}

    async def _publish(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "published"}

    def build(self) -> StateGraph[SimpleState]:
        graph: StateGraph[SimpleState] = StateGraph(SimpleState)
        graph.add_node("collect", self._collect)
        graph.add_node("assess", self._assess)
        graph.add_node("inspect", self._inspect)
        graph.add_node("decompose", self._decompose)
        graph.add_node("validate", self._validate)
        graph.add_node("publish", self._publish)
        graph.add_edge(START, "collect")
        graph.add_edge("collect", "assess")
        graph.add_edge("assess", "inspect")
        graph.add_edge("inspect", "decompose")
        graph.add_edge("decompose", "validate")
        graph.add_edge("validate", "publish")
        graph.add_edge("publish", END)
        return graph


class VerificationWorkflowBuilder:
    """Stages: build verification plan -> run deterministic checks ->
    structural analysis -> semantic verification -> aggregate evidence ->
    produce verdict -> create observation if necessary (Task 28.6)."""

    def __init__(self, container: BrainContainer) -> None:
        self._container = container

    async def _plan(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "plan"}

    async def _checks(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "checks"}

    async def _structural(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "structural"}

    async def _semantic(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "semantic"}

    async def _evidence(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "evidence"}

    async def _verdict(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "verdict"}

    async def _observe(self, state: SimpleState) -> SimpleState:
        return {**state, "status": "observed"}

    def build(self) -> StateGraph[SimpleState]:
        graph: StateGraph[SimpleState] = StateGraph(SimpleState)
        graph.add_node("plan", self._plan)
        graph.add_node("checks", self._checks)
        graph.add_node("structural", self._structural)
        graph.add_node("semantic", self._semantic)
        graph.add_node("evidence", self._evidence)
        graph.add_node("verdict", self._verdict)
        graph.add_node("observe", self._observe)
        graph.add_edge(START, "plan")
        graph.add_edge("plan", "checks")
        graph.add_edge("checks", "structural")
        graph.add_edge("structural", "semantic")
        graph.add_edge("semantic", "evidence")
        graph.add_edge("evidence", "verdict")
        graph.add_edge("verdict", "observe")
        graph.add_edge("observe", END)
        return graph


def build_ingestion_workflow(container: BrainContainer) -> StateGraph[SimpleState]:
    return IngestionWorkflowBuilder(container).build()


def build_planning_workflow(container: BrainContainer) -> StateGraph[SimpleState]:
    return PlanningWorkflowBuilder(container).build()


def build_verification_workflow(container: BrainContainer) -> StateGraph[SimpleState]:
    return VerificationWorkflowBuilder(container).build()


__all__ = [
    "build_engineering_workflow",
    "build_ingestion_workflow",
    "build_planning_workflow",
    "build_verification_workflow",
]
