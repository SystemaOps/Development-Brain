"""FastAPI dependencies (Phase 23).

Routes obtain the :class:`BrainContainer` from ``request.app.state.container``
which is installed by the lifespan handler.
"""

from __future__ import annotations

from fastapi import Request

from brain.bootstrap.container import BrainContainer


def get_container(request: Request) -> BrainContainer:
    container: BrainContainer = request.app.state.container
    return container
