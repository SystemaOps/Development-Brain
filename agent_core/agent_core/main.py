from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agent_core import models as _models  # noqa: F401
from agent_core.api.agents import router as agents_router
from agent_core.api.context import router as context_router
from agent_core.api.documents import router as documents_router
from agent_core.api.events import router as events_router
from agent_core.api.planning import router as planning_router
from agent_core.api.projects import router as projects_router
from agent_core.api.provisioning import router as provisioning_router
from agent_core.api.repositories import router as repositories_router
from agent_core.db import create_schema
from agent_core.workflow.checkpointer import get_checkpoint_database_url
from agent_core.workflow.store import build_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_schema()

    checkpoint_db_url = get_checkpoint_database_url()

    async with AsyncPostgresSaver.from_conn_string(checkpoint_db_url) as checkpointer:
        await checkpointer.setup()

        app.state.langgraph_checkpointer = checkpointer
        app.state.langgraph_store = build_store()

        yield


app = FastAPI(
    title="Planning Agent Core",
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(projects_router)
app.include_router(agents_router)
app.include_router(documents_router)
app.include_router(planning_router)
app.include_router(provisioning_router)
app.include_router(context_router)
app.include_router(events_router)
app.include_router(repositories_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
