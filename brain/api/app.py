"""FastAPI application factory (Phase 23).

``create_app`` builds the control plane from the same composition root as the
worker/scheduler/CLI.  Global DB clients are never constructed at import time;
everything is wired during the lifespan startup.
"""

from __future__ import annotations

from fastapi import FastAPI

from brain.api.correlation import CorrelationMiddleware
from brain.api.errors import register_error_handlers
from brain.api.lifespan import lifespan
from brain.api.routes import (
    capabilities,
    code,
    contexts,
    documents,
    executions,
    health,
    knowledge,
    observations,
    projects,
    pull_requests,
    repositories,
    requirements,
    system,
    verification,
    work_items,
)
from brain.bootstrap.settings import BrainSettings


def create_app(settings: BrainSettings | None = None) -> FastAPI:
    """Build the FastAPI application.

    ``settings`` may be provided explicitly (tests) or resolved from the
    environment during startup.
    """
    resolved_settings = settings or BrainSettings()

    app = FastAPI(
        title="Software Development Brain API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings

    app.add_middleware(CorrelationMiddleware)
    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(capabilities.router)
    app.include_router(system.router)
    app.include_router(projects.router)
    app.include_router(repositories.router)
    app.include_router(documents.router)
    app.include_router(requirements.router)
    app.include_router(work_items.router)
    app.include_router(contexts.router)
    app.include_router(code.router)
    app.include_router(knowledge.router)
    app.include_router(executions.router)
    app.include_router(verification.router)
    app.include_router(pull_requests.router)
    app.include_router(observations.router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "brain", "docs": "/docs"}

    return app
