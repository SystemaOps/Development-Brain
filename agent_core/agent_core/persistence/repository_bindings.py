from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.enums import RepositoryAccessMode
from agent_core.domain.repositories import RepositoryBinding
from agent_core.models import RepositoryBindingRecord, now_utc


class SqlAlchemyRepositoryBindingStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_binding(
        self,
        *,
        project_id: UUID,
        binding: RepositoryBinding,
    ) -> RepositoryBinding:
        stmt = (
            insert(RepositoryBindingRecord)
            .values(
                project_id=project_id,
                repository_key=binding.repository_key,
                mount_path=binding.mount_path,
                access_mode=binding.access_mode.value,
                write_allowlist=list(binding.write_allowlist),
                denylist=list(binding.denylist),
                command_allowlist=list(binding.command_allowlist),
            )
            .on_conflict_do_update(
                index_elements=[
                    RepositoryBindingRecord.project_id,
                    RepositoryBindingRecord.repository_key,
                ],
                set_={
                    "mount_path": binding.mount_path,
                    "access_mode": binding.access_mode.value,
                    "write_allowlist": list(binding.write_allowlist),
                    "denylist": list(binding.denylist),
                    "command_allowlist": list(binding.command_allowlist),
                    "updated_at": now_utc(),
                },
            )
            .returning(RepositoryBindingRecord.id)
        )
        binding_id = await self.db.scalar(stmt)
        if binding_id is None:
            raise RuntimeError("Repository binding upsert did not return an id")
        await self.db.commit()
        return binding

    async def get_binding(
        self,
        *,
        project_id: UUID,
        repository_key: str,
    ) -> RepositoryBinding | None:
        record = await self.db.scalar(
            select(RepositoryBindingRecord).where(
                RepositoryBindingRecord.project_id == project_id,
                RepositoryBindingRecord.repository_key == repository_key,
            )
        )
        if record is None:
            return None
        return _binding_from_record(record)


def _binding_from_record(record: RepositoryBindingRecord) -> RepositoryBinding:
    return RepositoryBinding(
        repository_key=record.repository_key,
        mount_path=record.mount_path,
        access_mode=RepositoryAccessMode(record.access_mode),
        write_allowlist=tuple(record.write_allowlist or ()),
        denylist=tuple(record.denylist or ()),
        command_allowlist=tuple(record.command_allowlist or ()),
    )
