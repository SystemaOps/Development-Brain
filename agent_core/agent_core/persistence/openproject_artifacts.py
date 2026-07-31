from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.models import ExternalArtifact, now_utc
from agent_core.ports.openproject import OpenProjectArtifactMapping


class SqlAlchemyOpenProjectArtifactStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_mapping(
        self,
        *,
        project_id: UUID,
        artifact_type: str,
        external_id: str,
        external_url: str | None = None,
        external_payload: dict[str, Any] | None = None,
        node_identity_id: UUID | None = None,
    ) -> OpenProjectArtifactMapping:
        payload = external_payload or {}
        update_values = {
            "project_id": project_id,
            "external_url": external_url,
            "external_payload": payload,
            "updated_at": now_utc(),
        }
        if node_identity_id is not None:
            update_values["node_identity_id"] = node_identity_id
        stmt = (
            insert(ExternalArtifact)
            .values(
                project_id=project_id,
                node_identity_id=node_identity_id,
                system_name="openproject",
                artifact_type=artifact_type,
                external_id=external_id,
                external_url=external_url,
                external_payload=payload,
            )
            .on_conflict_do_update(
                index_elements=[
                    ExternalArtifact.system_name,
                    ExternalArtifact.artifact_type,
                    ExternalArtifact.external_id,
                ],
                set_=update_values,
            )
            .returning(ExternalArtifact.id)
        )
        artifact_id = await self.db.scalar(stmt)
        if artifact_id is None:
            raise RuntimeError("OpenProject artifact upsert did not return an id")
        await self.db.commit()
        return OpenProjectArtifactMapping(
            artifact_id=artifact_id,
            project_id=project_id,
            node_identity_id=node_identity_id,
            artifact_type=artifact_type,
            external_id=external_id,
            external_url=external_url,
            external_payload=payload,
        )
