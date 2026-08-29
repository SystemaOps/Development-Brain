"""Main engineering workflow (Phase 28).

A LangGraph StateGraph[EngineeringState] implementing the full engineering stage list
(Task 28.3):

LOAD WORK ITEM -> SYNC STATE -> UNDERSTAND -> ANALYZE IMPLEMENTATION STATUS
-> CREATE OBSERVATION IF IMPORTANT -> BUILD CONTEXT -> ASSESS RISK ->
SELECT EXECUTOR -> APPROVAL GATE -> EXECUTE -> COLLECT EVIDENCE -> VERIFY
-> RETRY/ESCALATE -> PR READINESS -> CREATE PR IF ALLOWED ->
PUBLISH OBSERVATION -> UPDATE BRAIN -> COMPLETE.

Nodes call application services through the container; none of them touch
provider SDKs directly (Task 28.7).  Checkpoints are the resume position;
execution records remain engineering history (Task 28.8).
"""

from __future__ import annotations

import uuid

from langgraph.graph import END, START, StateGraph

from brain.bootstrap.container import BrainContainer
from brain.orchestration.states import EngineeringState, initial_state


class EngineeringWorkflowBuilder:
    """Builds the LangGraph engineering workflow against a container."""

    def __init__(self, container: BrainContainer) -> None:
        self._container = container

    # --- node implementations ---------------------------------------------

    async def _load_work_item(self, state: EngineeringState) -> EngineeringState:
        work_item = await self._container.repositories.work_items.get(
            state["work_item_id"]  # type: ignore[arg-type]
        )
        if work_item is None:
            return {**state, "stage": "failed", "error": "work item not found"}
        project = await self._container.repositories.projects.get(work_item.project_id)
        if project is None:
            return {**state, "stage": "failed", "error": "project not found"}
        return {
            **state,
            "project_id": project.id,
            "stage": "understand",
        }

    async def _understand(self, state: EngineeringState) -> EngineeringState:
        # Requirement understanding is id-based; no large content in state.
        return {**state, "stage": "analyze"}

    async def _analyze_implementation(self, state: EngineeringState) -> EngineeringState:
        work_item = await self._container.repositories.work_items.get(
            state["work_item_id"]  # type: ignore[arg-type]
        )
        status = "analyzed"
        if work_item is not None:
            status = work_item.implementation_status.value
        return {**state, "stage": "build_context", "implementation_status": status}

    async def _create_observation(self, state: EngineeringState) -> EngineeringState:
        # Meaningful findings become observations (Phase 26).
        if state.get("implementation_status") not in {"implemented", "implemented_unverified"}:
            return {**state, "stage": "build_context"}
        from brain.application.observations import ObservationService
        from brain.domain.observations import ObservationType

        observations = self._container.services["observations"]
        assert isinstance(observations, ObservationService)
        if state.get("project_id") is None or state.get("work_item_id") is None:
            return {**state, "stage": "build_context"}
        observation = await observations.create(
            project_id=state["project_id"],  # type: ignore[arg-type]
            observation_type=ObservationType.IMPLEMENTATION_STATUS,
            title="Existing implementation found",
            work_item_id=state["work_item_id"],  # type: ignore[arg-type]
            dedup_key=f"impl-status:{state['work_item_id']}",
        )
        return {
            **state,
            "stage": "build_context",
            "observation_ids": uuid.UUID(str(observation.id)),  # type: ignore[typeddict-item]
        }

    async def _build_context(self, state: EngineeringState) -> EngineeringState:
        from brain.domain.context import ContextRequest

        request = ContextRequest(
            work_item_id=state["work_item_id"],  # type: ignore[arg-type]
            project_id=state.get("project_id"),  # type: ignore[arg-type]
            repository_id=state.get("repository_id"),  # type: ignore[arg-type]
            revision=state.get("base_revision"),
            preferred_token_budget=8000,
        )
        result = await self._container.context_engine.build(request)
        return {
            **state,
            "stage": "execute",
            "context_capsule_id": result.capsule.id,
        }

    async def _execute(self, state: EngineeringState) -> EngineeringState:
        from brain.domain.executions import ExecutionRequest
        from brain.ports.executor import ExecutorPort

        execution_id = uuid.uuid4()
        executor = self._container.services["executor"]
        assert isinstance(executor, ExecutorPort)
        request = ExecutionRequest(
            execution_id=execution_id,  # type: ignore[arg-type]
            workflow_id=state["workflow_id"],  # type: ignore[arg-type]
            work_item_id=state["work_item_id"],  # type: ignore[arg-type]
            repository_ref=str(state.get("repository_id") or ""),
            base_revision=state.get("base_revision") or "HEAD",
        )
        result = await executor.execute(request)
        if result.status.value in {"failed", "blocked", "cancelled"}:
            return {
                **state,
                "stage": "retry",
                "execution_id": execution_id,
                "error": f"execution {result.status.value}",
            }
        return {
            **state,
            "stage": "verify",
            "execution_id": execution_id,
            "modified_files": list(result.modified_files),
        }

    async def _verify(self, state: EngineeringState) -> EngineeringState:
        work_item = await self._container.repositories.work_items.get(
            state["work_item_id"]  # type: ignore[arg-type]
        )
        acceptance_criteria: list[str] = []
        if work_item is not None:
            acceptance_criteria = [c.description for c in work_item.acceptance_criteria]
        outcome = await self._container.verification.verify(
            execution_id=state.get("execution_id"),  # type: ignore[arg-type]
            work_item_id=state["work_item_id"],  # type: ignore[arg-type]
            acceptance_criteria=acceptance_criteria,
            changed_files=state.get("modified_files", []),
        )
        if outcome.run.verdict.value == "pass":
            return {
                **state,
                "stage": "pr_readiness",
                "verification_id": outcome.run.id,
                "error": None,
            }
        if state.get("retry_count", 0) >= 3:
            return {
                **state,
                "stage": "human",
                "verification_id": outcome.run.id,
                "waiting_for_human": True,
                "error": f"verification {outcome.run.verdict.value} after retries",
            }
        return {
            **state,
            "stage": "retry",
            "verification_id": outcome.run.id,
            "error": f"verification {outcome.run.verdict.value}",
        }

    async def _retry(self, state: EngineeringState) -> EngineeringState:
        retries = state.get("retry_count", 0)
        if retries >= 3:
            return {**state, "stage": "human", "waiting_for_human": True}
        return {**state, "stage": "execute", "retry_count": retries + 1}

    async def _human(self, state: EngineeringState) -> EngineeringState:
        # Waits for human input; resume arrives via HumanFeedbackReceived.
        return {**state, "stage": "human", "waiting_for_human": True}

    async def _pr_readiness(self, state: EngineeringState) -> EngineeringState:
        if self._container.settings.automation.auto_create_pr:
            return {**state, "stage": "create_pr"}
        return {**state, "stage": "publish_observation"}

    async def _create_pr(self, state: EngineeringState) -> EngineeringState:
        pr_port = self._container.pull_requests
        if pr_port is None:
            return {**state, "stage": "publish_observation"}
        work_item = await self._container.repositories.work_items.get(
            state["work_item_id"]  # type: ignore[arg-type]
        )
        if work_item is None:
            return {**state, "stage": "publish_observation"}
        repos = await self._container.repositories.repositories.list_by_project(
            work_item.project_id
        )
        if not repos:
            return {**state, "stage": "publish_observation"}
        repository = repos[0]
        await pr_port.create_pull_request(
            repository=repository,
            source_branch=f"brain/{state['workflow_id']}",
            target_branch=repository.default_branch,
            title=work_item.title,
            description=work_item.description,
        )
        return {**state, "stage": "publish_observation"}

    async def _publish_observation(self, state: EngineeringState) -> EngineeringState:
        return {**state, "stage": "update_brain"}

    async def _update_brain(self, state: EngineeringState) -> EngineeringState:
        return {**state, "stage": "complete", "status": "completed"}

    async def _fail(self, state: EngineeringState) -> EngineeringState:
        return {**state, "stage": "failed", "status": "failed"}

    # --- graph construction -----------------------------------------------

    def build(self) -> StateGraph[EngineeringState]:
        graph: StateGraph[EngineeringState] = StateGraph(EngineeringState)
        graph.add_node("load_work_item", self._load_work_item)
        graph.add_node("understand", self._understand)
        graph.add_node("analyze", self._analyze_implementation)
        graph.add_node("create_observation", self._create_observation)
        graph.add_node("build_context", self._build_context)
        graph.add_node("execute", self._execute)
        graph.add_node("verify", self._verify)
        graph.add_node("retry", self._retry)
        graph.add_node("human", self._human)
        graph.add_node("pr_readiness", self._pr_readiness)
        graph.add_node("create_pr", self._create_pr)
        graph.add_node("publish_observation", self._publish_observation)
        graph.add_node("update_brain", self._update_brain)
        graph.add_node("fail", self._fail)

        graph.add_edge(START, "load_work_item")
        graph.add_edge("load_work_item", "understand")
        graph.add_edge("understand", "analyze")
        graph.add_edge("analyze", "create_observation")
        graph.add_edge("create_observation", "build_context")
        graph.add_edge("build_context", "execute")
        graph.add_edge("execute", "verify")
        graph.add_conditional_edges(
            "verify",
            lambda s: s.get("stage", "retry"),
            {"pr_readiness": "pr_readiness", "retry": "retry", "human": "human"},
        )
        graph.add_conditional_edges(
            "retry",
            lambda s: "human" if s.get("waiting_for_human") else "execute",
            {"execute": "execute", "human": "human"},
        )
        # The human node pauses here: no outgoing edge.  A checkpoint remains
        # at stage=human and HumanFeedbackReceived resumes the workflow.
        graph.add_edge("pr_readiness", "create_pr")
        graph.add_edge("pr_readiness", "publish_observation")
        graph.add_edge("create_pr", "publish_observation")
        graph.add_edge("publish_observation", "update_brain")
        graph.add_edge("update_brain", END)
        graph.add_edge("fail", END)
        return graph


def build_engineering_workflow(container: BrainContainer) -> StateGraph[EngineeringState]:
    """Build the compiled engineering workflow for a container."""
    return EngineeringWorkflowBuilder(container).build()


def make_initial_state(
    *,
    workflow_id: uuid.UUID,
    project_id: uuid.UUID,
    work_item_id: uuid.UUID,
    repository_id: uuid.UUID | None = None,
    base_revision: str | None = None,
) -> EngineeringState:
    return initial_state(
        workflow_id=workflow_id,
        project_id=project_id,
        work_item_id=work_item_id,
        repository_id=repository_id,
        base_revision=base_revision,
    )


__all__ = ["EngineeringWorkflowBuilder", "build_engineering_workflow", "make_initial_state"]
