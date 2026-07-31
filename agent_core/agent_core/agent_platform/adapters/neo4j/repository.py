from __future__ import annotations

from agent_core.ports.graph_store import GraphStorePort


class GraphRepository(GraphStorePort):
    """Platform-facing graph repository interface for Neo4j-backed relationships."""


__all__ = ["GraphRepository"]
