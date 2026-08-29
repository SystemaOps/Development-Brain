"""Audit trail port + reference implementation (Task 40.7)."""

from __future__ import annotations

from typing import Protocol

from brain.domain.audit import AuditEvent


class AuditLog(Protocol):
    async def record(self, event: AuditEvent) -> AuditEvent: ...

    async def list(self, *, limit: int = 100, action: str | None = None) -> list[AuditEvent]: ...


class InMemoryAuditLog:
    """In-memory reference implementation."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> AuditEvent:
        self._events.append(event)
        return event

    async def list(self, *, limit: int = 100, action: str | None = None) -> list[AuditEvent]:
        events = [e for e in self._events if action is None or e.action.value == action]
        return events[-limit:]


__all__ = ["AuditLog", "InMemoryAuditLog"]
