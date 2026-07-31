from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.coding import CodingAttemptResult
from agent_core.models import CodingAttemptRecord, now_utc


class SqlAlchemyCodingAttemptStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def next_attempt_number(
        self,
        *,
        project_id: UUID,
        repository_key: str,
        task_key: str,
    ) -> int:
        latest = await self.db.scalar(
            select(func.max(CodingAttemptRecord.attempt_number)).where(
                CodingAttemptRecord.project_id == project_id,
                CodingAttemptRecord.repository_key == repository_key,
                CodingAttemptRecord.task_key == task_key,
            )
        )
        return int(latest or 0) + 1

    async def record_result(
        self,
        *,
        project_id: UUID,
        result: CodingAttemptResult,
    ) -> UUID:
        values = {
            "project_id": project_id,
            "repository_key": result.repository_key,
            "task_key": result.task_key,
            "attempt_number": result.attempt_number,
            "status": result.status.value,
            "base_commit_sha": result.base_commit_sha,
            "branch": result.branch,
            "changed_files": result.changed_files,
            "command_results": [item.model_dump(mode="json") for item in result.command_results],
            "evidence": [item.model_dump(mode="json") for item in result.evidence],
            "rollback_plan": result.rollback_plan.model_dump(mode="json"),
            "final_diff": result.final_diff,
            "error_summary": {"errors": result.errors},
            "updated_at": now_utc(),
        }
        stmt = (
            insert(CodingAttemptRecord)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[
                    CodingAttemptRecord.project_id,
                    CodingAttemptRecord.repository_key,
                    CodingAttemptRecord.task_key,
                    CodingAttemptRecord.attempt_number,
                ],
                set_={key: value for key, value in values.items() if key != "project_id"},
            )
            .returning(CodingAttemptRecord.id)
        )
        attempt_id = await self.db.scalar(stmt)
        if attempt_id is None:
            raise RuntimeError("Coding attempt record upsert did not return an id")
        await self.db.commit()
        return attempt_id
