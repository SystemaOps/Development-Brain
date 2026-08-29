"""CLI command groups (Phase 30)."""

from __future__ import annotations

import typer

from brain.cli.commands.contexts import context_app
from brain.cli.commands.executions import execution_app
from brain.cli.commands.observations import observation_app
from brain.cli.commands.projects import project_app
from brain.cli.commands.repositories import repository_app
from brain.cli.commands.runtime import runtime_app
from brain.cli.commands.work_items import work_item_app


def build_cli() -> typer.Typer:
    """Build the brainctl application.

    Runtime commands (status/health/capabilities) live at the top level;
    the rest are grouped subcommands.
    """
    app = typer.Typer(help="Software Development Brain control plane.")
    app.add_typer(runtime_app)
    app.add_typer(project_app, name="project")
    app.add_typer(repository_app, name="repository")
    app.add_typer(context_app, name="context")
    app.add_typer(work_item_app, name="work-item")
    app.add_typer(execution_app, name="execution")
    app.add_typer(observation_app, name="observation")
    return app


__all__ = ["build_cli"]
