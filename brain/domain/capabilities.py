"""Capability domain model (Phase 22).

Makes runtime capability availability explicit and queryable.  A capability
has a stable :class:`CapabilityName`, a :class:`CapabilityStatus`, an optional
provider, and a :class:`CapabilityHealth` snapshot (status + detail + checked
at).  The runtime uses this model instead of inferring availability from
exceptions during normal workflows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CapabilityName(StrEnum):
    POSTGRES = "postgres"
    NEO4J = "neo4j"
    WEAVIATE = "weaviate"
    REDIS = "redis"
    WORK_MANAGEMENT = "work_management"
    DOCUMENTATION_GIT = "documentation_git"
    DOCUMENTATION_XWIKI = "documentation_xwiki"
    DOCUMENT_CONVERSION = "document_conversion"
    SOFTWARE_CATALOG = "software_catalog"
    SOURCE_CONTROL = "source_control"
    CODING_EXECUTOR = "coding_executor"


class CapabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    MISCONFIGURED = "MISCONFIGURED"


class CapabilityHealth(BaseModel):
    """Result of one health check for a capability."""

    status: CapabilityStatus = CapabilityStatus.UNAVAILABLE
    detail: str = ""
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_usable(self) -> bool:
        return self.status in {
            CapabilityStatus.AVAILABLE,
            CapabilityStatus.DEGRADED,
        }


class CapabilityDescriptor(BaseModel):
    """One capability and its runtime state."""

    name: CapabilityName
    provider: str = ""
    required: bool = False
    health: CapabilityHealth = Field(default_factory=CapabilityHealth)

    @property
    def status(self) -> CapabilityStatus:
        return self.health.status


__all__ = [
    "CapabilityDescriptor",
    "CapabilityHealth",
    "CapabilityName",
    "CapabilityStatus",
]
