"""Neo4j connection configuration.

Settings are read from environment variables with sensible local-development
defaults so the adapter works out of the box against the ``compose.yaml``
service while remaining overridable for tests and containers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Neo4jSettings:
    """Immutable settings used to connect to Neo4j."""

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"

    @classmethod
    def from_env(cls) -> Neo4jSettings:
        """Build settings from ``BRAIN_NEO4J_URI`` and friends."""
        return cls(
            uri=os.getenv("BRAIN_NEO4J_URI", cls.uri),
            user=os.getenv("BRAIN_NEO4J_USER", cls.user),
            password=os.getenv("BRAIN_NEO4J_PASSWORD", cls.password),
            database=os.getenv("BRAIN_NEO4J_DATABASE", cls.database),
        )
