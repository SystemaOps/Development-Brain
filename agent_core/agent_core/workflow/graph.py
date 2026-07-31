from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.skills.registry import SkillRegistry
from agent_core.workflow.nodes import make_nodes
from agent_core.workflow.routing import route_after_skill
from agent_core.workflow.state import PlanningGraphState


def build_planning_graph(
    db: AsyncSession | None,
    checkpointer,
    store,
    *,
    registry: SkillRegistry | None = None,
    planning_service=None,
    capsule_service=None,
):
    nodes = make_nodes(
        db,
        registry=registry,
        planning_service=planning_service,
        capsule_service=capsule_service,
    )

    graph = StateGraph(PlanningGraphState)

    graph.add_node("load_session", nodes["load_session"])
    graph.add_node("route_skill", nodes["route_skill"])
    graph.add_node("run_selected_skill", nodes["run_selected_skill"])
    graph.add_node("save_clarification_questions", nodes["save_clarification_questions"])
    graph.add_node("persist_plan", nodes["persist_plan"])
    graph.add_node("build_context_capsules", nodes["build_context_capsules"])

    graph.add_edge(START, "load_session")
    graph.add_edge("load_session", "route_skill")
    graph.add_edge("route_skill", "run_selected_skill")

    graph.add_conditional_edges(
        "run_selected_skill",
        route_after_skill,
        {
            "save_questions": "save_clarification_questions",
            "plan": "route_skill",
            "persist_plan": "persist_plan",
            "finish": END,
        },
    )

    graph.add_edge("save_clarification_questions", END)
    graph.add_edge("persist_plan", "build_context_capsules")
    graph.add_edge("build_context_capsules", END)

    return graph.compile(
        checkpointer=checkpointer,
        store=store,
    )
