from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.deps import get_db
from agent_core.schemas import ContextCapsuleView
from agent_core.services.context_capsule_service import ContextCapsuleService

router = APIRouter(prefix="/v1/context", tags=["context"])


@router.post("/plan-nodes/{plan_node_id}/capsule", response_model=ContextCapsuleView)
async def build_capsule(plan_node_id: UUID, capsule_type: str = "execution", db: AsyncSession = Depends(get_db)):
    try:
        capsule = await ContextCapsuleService(db).build_for_node(plan_node_id, capsule_type)
    except KeyError:
        raise HTTPException(status_code=404, detail="Plan node not found")
    return ContextCapsuleView(id=capsule.id, plan_node_id=capsule.plan_node_id, capsule_type=capsule.capsule_type, content=capsule.content, token_estimate=capsule.token_estimate)
