from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Request

from agent_core.api.deps import get_db
from agent_core.models import ClarificationQuestion, PlanningSession, PlanVersion, Project
from agent_core.schemas import AnswerQuestionsRequest, ClarificationQuestionView, PlanningSessionCreate, PlanningSessionView, PlanVersionView
from agent_core.services.planning_service import PlanningService
from agent_core.workflow.runner import PlanningWorkflowRunner

router = APIRouter(prefix="/v1/planning", tags=["planning"])


async def session_view(db: AsyncSession, session: PlanningSession) -> PlanningSessionView:
    project = await db.get(Project, session.project_id)
    qs = await db.scalars(select(ClarificationQuestion).where(ClarificationQuestion.planning_session_id == session.id).order_by(ClarificationQuestion.created_at))
    return PlanningSessionView(
        id=session.id,
        project_key=project.project_key,
        status=session.status,
        input_mode=session.input_mode,
        original_request=session.original_request,
        questions=[ClarificationQuestionView(id=q.id, question_key=q.question_key, question=q.question, reason=q.reason, blocking=q.blocking, answer_format=q.answer_format, answer=q.answer, status=q.status) for q in qs],
    )

@router.post("/sessions/{session_id}/run")
async def run_planning_workflow(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    runner = PlanningWorkflowRunner(
        db=db,
        checkpointer=request.app.state.langgraph_checkpointer,
        store=request.app.state.langgraph_store,
    )

    result = await runner.run(session_id)

    return {
        "session_id": str(session_id),
        "thread_id": f"planning-session-{session_id}",
        "selected_skill": result.get("selected_skill"),
        "ambiguity_status": result.get("ambiguity_status"),
        "plan_version_id": (
            str(result["plan_version_id"])
            if result.get("plan_version_id")
            else None
        ),
        "clarification_questions": result.get("clarification_questions", []),
        "context_capsule_ids": [
            str(item) for item in result.get("context_capsule_ids", [])
        ],
    }

@router.post("/sessions", response_model=PlanningSessionView)
async def start_session(payload: PlanningSessionCreate, db: AsyncSession = Depends(get_db)):
    try:
        session = await PlanningService(db).start_session(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    return await session_view(db, session)


@router.get("/sessions/{session_id}", response_model=PlanningSessionView)
async def get_session(session_id: UUID, db: AsyncSession = Depends(get_db)):
    session = await db.get(PlanningSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return await session_view(db, session)

@router.post("/sessions/{session_id}/run")
async def run_planning_workflow(
        session_id: UUID,
        db: AsyncSession = Depends(get_db),
    ):
    try:
        result = await PlanningWorkflowRunner(db).run(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "session_id": str(session_id),
        "status": result.get("ambiguity_status", "completed"),
        "plan_version_id": (
            str(result["plan_version_id"])
            if result.get("plan_version_id")
            else None
        ),
        "provisioning_job_ids": [
            str(job_id) for job_id in result.get("provisioning_job_ids", [])
        ],
        "clarification_questions": result.get("clarification_questions", []),
    }

@router.post("/sessions/{session_id}/answers", response_model=PlanningSessionView)
async def answer_questions(session_id: UUID, payload: AnswerQuestionsRequest, db: AsyncSession = Depends(get_db)):
    try:
        session = await PlanningService(db).answer_questions(session_id, payload.answers)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return await session_view(db, session)


@router.post("/sessions/{session_id}/draft-plan", response_model=PlanVersionView)
async def draft_plan(session_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        version = await PlanningService(db).draft_plan(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    project = await db.get(Project, version.project_id)
    return PlanVersionView(id=version.id, project_key=project.project_key, version_number=version.version_number, status=version.status, summary=version.summary)


@router.post("/plan-versions/{plan_version_id}/approve", response_model=PlanVersionView)
async def approve_plan(plan_version_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        version = await PlanningService(db).approve_plan(plan_version_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Plan version not found")
    project = await db.get(Project, version.project_id)
    return PlanVersionView(id=version.id, project_key=project.project_key, version_number=version.version_number, status=version.status, summary=version.summary)
