from __future__ import annotations

from langgraph.store.memory import InMemoryStore


def build_store():
    """
    Start with InMemoryStore for development.

    Later replace with a persistent store implementation if needed.
    Your authoritative long-term project memory is still:
    - PostgreSQL
    - Neo4j
    - Weaviate
    """
    return InMemoryStore()