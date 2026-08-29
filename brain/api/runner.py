"""API runner (Phase 31).

Wraps Uvicorn configuration for ``brain-api``: host, port, log level, workers.
Settings come from ``BRAIN_API_*`` environment variables with sensible local
defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import uvicorn

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_LOG_LEVEL = "info"
DEFAULT_WORKERS = 1


@dataclass(frozen=True)
class RunnerSettings:
    """Uvicorn configuration resolved for the API runner."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    log_level: str = DEFAULT_LOG_LEVEL
    workers: int = DEFAULT_WORKERS


def runner_settings() -> RunnerSettings:
    """Resolve Uvicorn settings from ``BRAIN_API_*`` environment variables."""
    return RunnerSettings(
        host=os.getenv("BRAIN_API_HOST", DEFAULT_HOST),
        port=int(os.getenv("BRAIN_API_PORT", str(DEFAULT_PORT))),
        log_level=os.getenv("BRAIN_API_LOG_LEVEL", DEFAULT_LOG_LEVEL),
        workers=int(os.getenv("BRAIN_API_WORKERS", str(DEFAULT_WORKERS))),
    )


def main() -> None:
    """Console entry point (registered as ``brain-api``)."""
    settings = runner_settings()
    uvicorn.run(
        "brain.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        workers=settings.workers,
    )


if __name__ == "__main__":
    main()
