from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.deps import get_db
from agent_core.application.project_orchestrator import ProjectEventOrchestrator
from agent_core.persistence.executions import SqlAlchemyAgentExecutionRecorder
from agent_core.persistence.event_inbox import SqlAlchemyEventInbox
from agent_core.services.agent_platform_composition import (
    create_agent_platform_service_for_db,
)

router = APIRouter(prefix="/v1/events", tags=["events"])


@router.post("/{event_id}/orchestrate")
async def orchestrate_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
):
    orchestrator = ProjectEventOrchestrator(
        db=db,
        event_inbox=SqlAlchemyEventInbox(db),
        agent_platform_service=create_agent_platform_service_for_db(db),
        execution_recorder=SqlAlchemyAgentExecutionRecorder(db),
    )

    try:
        result = await orchestrator.handle_persisted_event(event_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return result.as_dict()
