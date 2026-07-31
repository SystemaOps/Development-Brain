from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.deps import get_db
from agent_core.models import Project
from agent_core.schemas import ProjectCreate, ProjectView

router = APIRouter(prefix="/v1/projects", tags=["projects"])


@router.post("", response_model=ProjectView)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(select(Project).where(Project.project_key == payload.project_key))
    if existing:
        raise HTTPException(status_code=409, detail="Project key already exists")
    project = Project(project_key=payload.project_key, name=payload.name, description=payload.description, source_type=payload.source_type, status="draft")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return ProjectView(id=project.id, project_key=project.project_key, name=project.name, description=project.description, status=project.status)


@router.get("/{project_key}", response_model=ProjectView)
async def get_project(project_key: str, db: AsyncSession = Depends(get_db)):
    project = await db.scalar(select(Project).where(Project.project_key == project_key))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectView(id=project.id, project_key=project.project_key, name=project.name, description=project.description, status=project.status)
