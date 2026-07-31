from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.workflow.graph import build_planning_graph


class PlanningWorkflowRunner:
    def __init__(self, db: AsyncSession, checkpointer, store):
        self.db = db
        self.checkpointer = checkpointer
        self.store = store

    async def run(self, session_id: UUID) -> dict:
        graph = build_planning_graph(
            db=self.db,
            checkpointer=self.checkpointer,
            store=self.store,
        )

        config = {
            "configurable": {
                "thread_id": f"planning-session-{session_id}",
            }
        }

        return await graph.ainvoke(
            {
                "session_id": session_id,
                "errors": [],
            },
            config=config,
        )
