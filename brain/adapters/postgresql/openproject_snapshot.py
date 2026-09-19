"""PostgreSQL OpenProject snapshot store.

Durable replacement for the in-memory snapshot store: normalized work-item
snapshots survive restarts so webhook/pull diffs never mistake existing state
for new state (bootstrap plan Phase 8).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from brain.adapters.postgresql.tables import OpenProjectSnapshotRow
from brain.application.openproject_parser import OpenProjectWorkItemSnapshot
from brain.ports.openproject_snapshot import OpenProjectSnapshotStore


class PostgresOpenProjectSnapshotStore(OpenProjectSnapshotStore):
    """OpenProjectSnapshotStore backed by the ``openproject_work_item_snapshots`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, external_id: str) -> OpenProjectWorkItemSnapshot | None:
        result = await self._session.execute(
            select(OpenProjectSnapshotRow).where(OpenProjectSnapshotRow.external_id == external_id)
        )
        row = result.scalar_one_or_none()
        return _snapshot_from_payload(row.snapshot) if row is not None else None

    async def save(self, snapshot: OpenProjectWorkItemSnapshot) -> None:
        row = await self._session.get(OpenProjectSnapshotRow, snapshot.external_id)
        payload = _snapshot_to_payload(snapshot)
        if row is None:
            self._session.add(
                OpenProjectSnapshotRow(
                    external_id=snapshot.external_id,
                    snapshot=payload,
                    updated_at=snapshot.updated_at,
                    ingested_at=datetime.now(UTC),
                )
            )
        else:
            row.snapshot = payload
            row.updated_at = snapshot.updated_at
        await self._session.flush()


def _snapshot_to_payload(snapshot: OpenProjectWorkItemSnapshot) -> dict[str, Any]:
    return dataclasses.asdict(snapshot)


def _snapshot_from_payload(payload: dict[str, Any] | None) -> OpenProjectWorkItemSnapshot | None:
    if not payload:
        return None
    kwargs: dict[str, Any] = {}
    for field in dataclasses.fields(OpenProjectWorkItemSnapshot):
        if field.name in payload:
            kwargs[field.name] = payload[field.name]
    return OpenProjectWorkItemSnapshot(**kwargs)


__all__ = ["PostgresOpenProjectSnapshotStore"]
