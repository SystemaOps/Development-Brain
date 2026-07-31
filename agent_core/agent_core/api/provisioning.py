from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.deps import get_db
from agent_core.schemas import ProvisionProjectResponse
from agent_core.services.provisioning_service import ProvisioningService

router = APIRouter(prefix="/v1/provisioning", tags=["provisioning"])


@router.post("/projects/{project_key}", response_model=ProvisionProjectResponse)
async def provision_project(project_key: str, db: AsyncSession = Depends(get_db)):
    try:
        return await ProvisioningService(db).enqueue_project_projection(project_key)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
