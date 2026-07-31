from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.models import PlanVersion, Project, ProvisioningJob
from agent_core.schemas import ProvisionProjectResponse


class ProvisioningService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def enqueue_project_projection(self, project_key: str) -> ProvisionProjectResponse:
        project = await self.db.scalar(select(Project).where(Project.project_key == project_key))
        if not project:
            raise KeyError(project_key)
        version = await self.db.scalar(select(PlanVersion).where(
            PlanVersion.project_id == project.id,
            PlanVersion.status == "active",
        ))
        if not version:
            raise ValueError("No active approved plan exists")
        jobs = [
            ("create_openproject_project_and_work_packages", "openproject"),
            ("upsert_neo4j_plan", "neo4j"),
            ("upsert_weaviate_memory", "weaviate"),
        ]
        created = []
        for job_type, system in jobs:
            job = ProvisioningJob(
                project_id=project.id,
                job_type=job_type,
                idempotency_key=f"{project.project_key}:{system}:v{version.version_number}",
                status="pending",
                payload_json={"project_key": project.project_key, "plan_version_id": str(version.id)},
            )
            self.db.add(job)
            created.append(job)
        await self.db.commit()
        for job in created:
            await self.db.refresh(job)
        return ProvisionProjectResponse(project_key=project.project_key, jobs_created=len(created), job_ids=[j.id for j in created])
