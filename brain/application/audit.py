"""Audit service (Task 40.7).

Wraps the :class:`AuditLog` port with convenience methods used by the
command dispatcher, execution handler, verification, PR service and
observation projection.
"""

from __future__ import annotations

import uuid

from brain.domain.audit import AuditAction, AuditEvent
from brain.domain.identity_auth import Identity
from brain.ports.audit import AuditLog


class AuditService:
    """Records structured audit events."""

    def __init__(self, log: AuditLog) -> None:
        self._log = log

    async def record(
        self,
        *,
        action: AuditAction,
        actor: str,
        actor_role: str = "",
        project_id: uuid.UUID | None = None,
        work_item_id: uuid.UUID | None = None,
        execution_id: uuid.UUID | None = None,
        repository_id: uuid.UUID | None = None,
        details: dict[str, object] | None = None,
    ) -> AuditEvent:
        return await self._log.record(
            AuditEvent(
                action=action,
                actor=actor,
                actor_role=actor_role,
                project_id=project_id,
                work_item_id=work_item_id,
                execution_id=execution_id,
                repository_id=repository_id,
                details=details or {},
            )
        )

    async def from_identity(
        self,
        identity: Identity | None,
        *,
        action: AuditAction,
        **context: object,
    ) -> AuditEvent:
        actor = identity.name if identity else "system"
        role = identity.role.value if identity else "system"
        identity_keys = {"project_id", "work_item_id", "execution_id", "repository_id"}
        details = {
            key: value
            for key, value in context.items()
            if value is not None and key not in identity_keys
        }
        return await self.record(
            action=action,
            actor=actor,
            actor_role=role,
            project_id=_uuid(context.get("project_id")),
            work_item_id=_uuid(context.get("work_item_id")),
            execution_id=_uuid(context.get("execution_id")),
            repository_id=_uuid(context.get("repository_id")),
            details=details,
        )

    async def list(self, *, limit: int = 100, action: str | None = None) -> list[AuditEvent]:
        return await self._log.list(limit=limit, action=action)


def _uuid(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None


__all__ = ["AuditService"]
