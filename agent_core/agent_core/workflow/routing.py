from __future__ import annotations

from agent_core.workflow.state import PlanningGraphState


def route_after_skill(state: PlanningGraphState) -> str:
    if state.get("clarification_questions"):
        return "save_questions"

    if state.get("plan"):
        return "persist_plan"

    if state.get("ambiguity_status") == "ready_for_planning":
        return "plan"

    return "finish"
