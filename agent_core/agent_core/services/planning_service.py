from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.llm import StructuredLLM
from agent_core.models import (
    ClarificationQuestion,
    PlanNode,
    PlanNodeIdentity,
    PlanNodeRelation,
    PlanVersion,
    PlanningSession,
    Project,
)
from agent_core.prompts import AMBIGUITY_SYSTEM, PLANNER_SYSTEM
from agent_core.schemas import PlanningSessionCreate, ProjectPlanSpec
from agent_core.enums import PlanningSessionStatus


class ClarificationQuestionSpec(BaseModel):
    question_key: str
    question: str
    reason: str
    blocking: bool = True
    answer_format: str | None = None


class AmbiguityAssessment(BaseModel):
    is_clear_enough: bool
    understood_goal: str
    questions: list[ClarificationQuestionSpec] = Field(default_factory=list)


class PlanningService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = StructuredLLM()

    async def start_session(self, payload: PlanningSessionCreate) -> PlanningSession:
        project = await self.db.scalar(select(Project).where(Project.project_key == payload.project_key))
        if not project:
            raise KeyError(payload.project_key)
        project.status = "planning"
        session = PlanningSession(
            project_id=project.id,
            input_mode=payload.input_mode,
            original_request=payload.original_request,
            intake_json=payload.intake,
            status="intake",
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return await self.assess_ambiguity(session.id)
    
    async def load_session_context(self, session_id: UUID) -> dict:
        session = await self.db.get(PlanningSession, session_id)
        if not session:
            raise KeyError(f"Planning session not found: {session_id}")

        project = await self.db.get(Project, session.project_id)
        if not project:
            raise KeyError(f"Project not found for session: {session_id}")

        return {
            "session_id": session.id,
            "project_id": project.id,
            "project_key": project.project_key,
            "original_request": session.original_request or "",
            "input_mode": session.input_mode,
            "intake": session.intake_json or {},
        }

    async def save_questions_from_graph(
        self,
        *,
        session_id: UUID,
        project_id: UUID,
        questions: list[dict],
    ) -> None:
        session = await self.db.get(PlanningSession, session_id)
        session.status = PlanningSessionStatus.NEEDS_CLARIFICATION

        for q in questions:
            self.db.add(
                ClarificationQuestion(
                    project_id=project_id,
                    planning_session_id=session_id,
                    question_key=q["question_key"],
                    question=q["question"],
                    reason=q["reason"],
                    blocking=q.get("blocking", True),
                    answer_format=q.get("answer_format"),
                    status="open",
                )
            )

        await self.db.commit()

    async def mark_ready_for_planning(self, session_id: UUID) -> None:
        session = await self.db.get(PlanningSession, session_id)
        session.status = PlanningSessionStatus.READY_FOR_PLANNING
        await self.db.commit()

    async def assess_ambiguity(self, session_id: UUID) -> PlanningSession:
        session = await self.db.get(PlanningSession, session_id)
        if not session:
            raise KeyError(session_id)
        try:
            assessment = await self.llm.generate(
                system=AMBIGUITY_SYSTEM,
                user=str({"request": session.original_request, "intake": session.intake_json}),
                output_model=AmbiguityAssessment,
            )
        except Exception:
            assessment = AmbiguityAssessment(
                is_clear_enough=False,
                understood_goal=session.original_request or "",
                questions=[ClarificationQuestionSpec(
                    question_key="mvp_boundary",
                    question="What is inside the MVP boundary and what is explicitly excluded?",
                    reason="The answer changes Epic, Story and Task decomposition.",
                    blocking=True,
                    answer_format="List included and excluded capabilities.",
                )],
            )

        old = await self.db.scalars(select(ClarificationQuestion).where(
            ClarificationQuestion.planning_session_id == session.id,
            ClarificationQuestion.status == "open",
        ))
        for q in old:
            q.status = "obsolete"

        if not assessment.is_clear_enough:
            session.status = "needs_clarification"
            for q in assessment.questions:
                self.db.add(ClarificationQuestion(
                    project_id=session.project_id,
                    planning_session_id=session.id,
                    question_key=q.question_key,
                    question=q.question,
                    reason=q.reason,
                    blocking=q.blocking,
                    answer_format=q.answer_format,
                    status="open",
                ))
        else:
            session.status = "ready_for_planning"
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def answer_questions(self, session_id: UUID, answers: dict[str, str]) -> PlanningSession:
        session = await self.db.get(PlanningSession, session_id)
        if not session:
            raise KeyError(session_id)
        questions = await self.db.scalars(select(ClarificationQuestion).where(
            ClarificationQuestion.planning_session_id == session.id,
            ClarificationQuestion.status == "open",
        ))
        by_key = {q.question_key: q for q in questions}
        for key, answer in answers.items():
            if key in by_key:
                by_key[key].answer = answer
                by_key[key].answered_at = datetime.utcnow()
                by_key[key].status = "answered"
        session.intake_json.setdefault("answers", {}).update(answers)
        await self.db.commit()
        return await self.assess_ambiguity(session.id)

    async def draft_plan(self, session_id: UUID) -> PlanVersion:
        session = await self.db.get(PlanningSession, session_id)
        if not session:
            raise KeyError(session_id)
        if session.status == "needs_clarification":
            raise ValueError("Answer blocking questions before drafting a plan")
        project = await self.db.get(Project, session.project_id)
        plan = await self._generate_plan(project, session)
        version_number = int(await self.db.scalar(select(func.max(PlanVersion.version_number)).where(PlanVersion.project_id == project.id)) or 0) + 1
        version = PlanVersion(
            project_id=project.id,
            planning_session_id=session.id,
            version_number=version_number,
            status="awaiting_review",
            summary=plan.summary,
            rationale=plan.rationale,
            generated_from=session.input_mode,
            plan_json=plan.model_dump(mode="json"),
        )
        self.db.add(version)
        await self.db.flush()
        await self._persist_nodes(project, version, plan)
        session.status = "plan_drafted"
        project.status = "awaiting_review"
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def approve_plan(self, plan_version_id: UUID) -> PlanVersion:
        version = await self.db.get(PlanVersion, plan_version_id)
        if not version:
            raise KeyError(plan_version_id)
        old_active = await self.db.scalars(select(PlanVersion).where(
            PlanVersion.project_id == version.project_id,
            PlanVersion.status == "active",
        ))
        for old in old_active:
            old.status = "superseded"
        version.status = "active"
        version.approved_at = datetime.utcnow()
        project = await self.db.get(Project, version.project_id)
        project.status = "active"
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def _generate_plan(self, project: Project, session: PlanningSession) -> ProjectPlanSpec:
        try:
            return await self.llm.generate(
                system=PLANNER_SYSTEM,
                user=str({"project_key": project.project_key, "project_name": project.name, "request": session.original_request, "intake": session.intake_json}),
                output_model=ProjectPlanSpec,
            )
        except Exception:
            return ProjectPlanSpec(
                summary="Core planning agent MVP with clarification, versioned planning, context capsules and artifact projection.",
                rationale="Fallback plan generated because the LLM endpoint was unavailable.",
                requirements=[{"key": "ask-when-unclear", "text": "Ask clarification questions before planning if input is unclear."}],
                constraints=[{"key": "postgres-source-of-truth", "text": "PostgreSQL is the source of truth."}],
                decisions=[{"key": "logical-project-namespace", "title": "Use project_key", "decision": "Use logical project_key namespace across stores."}],
                assumptions=[{"key": "openproject-types", "text": "OpenProject supports Epic, Story, and Task work package types."}],
                risks=[{"key": "large-readme", "text": "Large README can overflow context.", "mitigation": "Chunk and summarize before planning."}],
                components=[
                    {"key": "planning-api", "name": "Planning API", "component_type": "api"},
                    {"key": "openproject-adapter", "name": "OpenProject Adapter", "component_type": "adapter"},
                ],
                nodes=[
                    {"stable_key": "vision.core-agent", "kind": "vision", "title": "Self-hosted coding agent", "objective": "Build a self-hosted coding agent that preserves project intent across planning and execution."},
                    {"stable_key": "capability.planning", "kind": "capability", "title": "Planning Agent", "objective": "Convert requests and README files into versioned, validated plans.", "parent_stable_key": "vision.core-agent"},
                    {"stable_key": "epic.planning-flow", "kind": "epic", "title": "Planning workflow", "objective": "Support intake, clarification, plan drafting, review and approval.", "parent_stable_key": "capability.planning"},
                    {"stable_key": "story.clarify-intent", "kind": "story", "title": "Clarify user intent", "objective": "The user receives blocking questions before misleading plans are created.", "parent_stable_key": "epic.planning-flow"},
                    {"stable_key": "task.clarification-api", "kind": "task", "title": "Implement clarification API", "objective": "Expose routes to ask and answer clarification questions.", "parent_stable_key": "story.clarify-intent", "expected_outputs": ["Planning session can move from needs_clarification to ready_for_planning."], "likely_components": ["planning-api"], "acceptance_criteria": [{"key": "ac.clarification", "statement": "Unclear input creates open blocking questions.", "verification_method": "integration_test"}]},
                ],
            )

    async def _persist_nodes(self, project: Project, version: PlanVersion, plan: ProjectPlanSpec) -> None:
        node_by_key = {}
        for spec in plan.nodes:
            identity = await self.db.scalar(select(PlanNodeIdentity).where(
                PlanNodeIdentity.project_id == project.id,
                PlanNodeIdentity.stable_key == spec.stable_key,
            ))
            if not identity:
                identity = PlanNodeIdentity(project_id=project.id, stable_key=spec.stable_key, kind=spec.kind)
                self.db.add(identity)
                await self.db.flush()
            node = PlanNode(
                project_id=project.id,
                plan_version_id=version.id,
                node_identity_id=identity.id,
                kind=spec.kind,
                title=spec.title,
                objective=spec.objective,
                rationale=spec.rationale,
                inherited_context=spec.inherited_context,
                local_constraints=spec.local_constraints,
                assumptions=spec.assumptions,
                expected_outputs=spec.expected_outputs,
                likely_components=spec.likely_components,
                priority=spec.priority,
                size_estimate=spec.size_estimate,
                status="proposed",
                node_json=spec.model_dump(mode="json"),
            )
            self.db.add(node)
            await self.db.flush()
            identity.current_plan_node_id = node.id
            node_by_key[spec.stable_key] = node
        for spec in plan.nodes:
            node = node_by_key[spec.stable_key]
            if spec.parent_stable_key:
                self.db.add(PlanNodeRelation(
                    project_id=project.id,
                    plan_version_id=version.id,
                    from_node_id=node.id,
                    to_node_id=node_by_key[spec.parent_stable_key].id,
                    relation_type="child_of",
                ))
            for dep in spec.dependencies:
                self.db.add(PlanNodeRelation(
                    project_id=project.id,
                    plan_version_id=version.id,
                    from_node_id=node.id,
                    to_node_id=node_by_key[dep].id,
                    relation_type="depends_on",
                ))
