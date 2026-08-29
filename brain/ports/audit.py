"""Audit log port (Task 40.7)."""

from __future__ import annotations

from typing import Protocol

from brain.domain.audit import AuditEvent


class AuditLog(Protocol):
    async def record(self, event: AuditEvent) -> AuditEvent: ...

    async def list(self, *, limit: int = 100, action: str | None = None) -> list[AuditEvent]: ...


__all__ = ["AuditLog"]
