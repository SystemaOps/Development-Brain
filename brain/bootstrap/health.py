"""Runtime health probes (Phase 22).

Simple ``HealthCheckPort`` probes for the core storage adapters.  Each returns
a :class:`CapabilityHealth`.  Probes that cannot reach their target report
``UNAVAILABLE`` without raising (Task 22.2); the container wires them into the
capability registry for refresh (Task 22.4).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from brain.bootstrap.capabilities import HealthProbe
from brain.domain.capabilities import CapabilityHealth, CapabilityStatus
from brain.ports.knowledge_graph import KnowledgeGraphRepository
from brain.ports.semantic_index import SemanticIndex


def make_postgres_probe(
    session_factory: async_sessionmaker[AsyncSession],
) -> HealthProbe:
    async def _probe() -> CapabilityHealth:
        try:
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
            return CapabilityHealth(status=CapabilityStatus.AVAILABLE, detail="SELECT 1 ok")
        except Exception as exc:  # noqa: BLE001
            return CapabilityHealth(
                status=CapabilityStatus.UNAVAILABLE,
                detail=f"{type(exc).__name__}: {exc}",
            )

    return _probe


def make_neo4j_probe(graph: KnowledgeGraphRepository) -> HealthProbe:
    async def _probe() -> CapabilityHealth:
        health = getattr(graph, "health", None)
        if health is None:
            return CapabilityHealth(status=CapabilityStatus.AVAILABLE, detail="in-memory fallback")
        try:
            result = health()
            if hasattr(result, "__await__"):
                result = await result
            if isinstance(result, CapabilityHealth):
                return result
            return CapabilityHealth(
                status=CapabilityStatus.AVAILABLE if result else CapabilityStatus.UNAVAILABLE
            )
        except Exception as exc:  # noqa: BLE001
            return CapabilityHealth(
                status=CapabilityStatus.UNAVAILABLE,
                detail=f"{type(exc).__name__}: {exc}",
            )

    return _probe


def make_weaviate_probe(semantic: SemanticIndex) -> HealthProbe:
    async def _probe() -> CapabilityHealth:
        health = getattr(semantic, "health", None)
        if health is None:
            return CapabilityHealth(status=CapabilityStatus.AVAILABLE, detail="in-memory fallback")
        try:
            result = health()
            if hasattr(result, "__await__"):
                result = await result
            if isinstance(result, CapabilityHealth):
                return result
            return CapabilityHealth(
                status=CapabilityStatus.AVAILABLE if result else CapabilityStatus.UNAVAILABLE
            )
        except Exception as exc:  # noqa: BLE001
            return CapabilityHealth(
                status=CapabilityStatus.UNAVAILABLE,
                detail=f"{type(exc).__name__}: {exc}",
            )

    return _probe


__all__ = [
    "make_neo4j_probe",
    "make_postgres_probe",
    "make_weaviate_probe",
]
