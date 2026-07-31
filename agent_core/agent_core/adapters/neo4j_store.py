from __future__ import annotations

import re
from typing import Any

from neo4j import AsyncGraphDatabase

from agent_core.config import settings


_CYPHER_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Neo4jProjectionStore:
    def __init__(self) -> None:
        self.driver = AsyncGraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password))

    async def ensure_schema(self) -> None:
        await self.ensure_constraints()

    async def ensure_constraints(self) -> None:
        statements = [
            "CREATE CONSTRAINT project_key_unique IF NOT EXISTS FOR (p:Project) REQUIRE p.project_key IS UNIQUE",
            "CREATE CONSTRAINT plan_version_id_unique IF NOT EXISTS FOR (v:PlanVersion) REQUIRE v.id IS UNIQUE",
            "CREATE CONSTRAINT plan_node_id_unique IF NOT EXISTS FOR (n:PlanNode) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT repository_key_unique IF NOT EXISTS FOR (r:Repository) REQUIRE r.key IS UNIQUE",
            "CREATE CONSTRAINT code_symbol_key_unique IF NOT EXISTS FOR (s:CodeSymbol) REQUIRE s.key IS UNIQUE",
            "CREATE CONSTRAINT unresolved_code_reference_key_unique IF NOT EXISTS FOR (r:UnresolvedCodeReference) REQUIRE r.key IS UNIQUE",
        ]
        for statement in statements:
            await self.driver.execute_query(statement, database_=settings.neo4j_database)

    async def upsert_node(
        self,
        *,
        labels: tuple[str, ...],
        key: str,
        properties: dict[str, Any],
    ) -> None:
        label_clause = _label_clause(labels)
        await self.driver.execute_query(
            f"MERGE (n{label_clause} {{key: $key}}) SET n += $properties",
            key=key,
            properties={**properties, "key": key},
            database_=settings.neo4j_database,
        )

    async def upsert_relation(
        self,
        *,
        from_key: str,
        to_key: str,
        relation_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        safe_relation_type = _identifier(relation_type)
        await self.driver.execute_query(
            (
                "MATCH (source {key: $from_key}) "
                "MATCH (target {key: $to_key}) "
                f"MERGE (source)-[r:{safe_relation_type}]->(target) "
                "SET r += $properties"
            ),
            from_key=from_key,
            to_key=to_key,
            properties=properties or {},
            database_=settings.neo4j_database,
        )

    async def close(self) -> None:
        await self.driver.close()


def _label_clause(labels: tuple[str, ...]) -> str:
    if not labels:
        raise ValueError("At least one Neo4j label is required")
    return ":" + ":".join(_identifier(label) for label in labels)


def _identifier(value: str) -> str:
    if not _CYPHER_IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe Neo4j identifier: {value}")
    return value
