"""Shared enums and value objects used across the canonical domain model."""

from __future__ import annotations

from enum import StrEnum


class Priority(StrEnum):
    """Relative priority of a requirement or work item."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"
