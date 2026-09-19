"""Project commands: list, create, show (Phase 30.3)."""

from __future__ import annotations

import typer

from brain.cli.helpers import async_command, cli_container
from brain.domain.projects import Project

project_app = typer.Typer(help="Project operations.")


@project_app.command("list")
@async_command
async def list_projects() -> None:
    """List projects."""
    async with cli_container() as container:
        projects = await container.repositories.projects.list()
        for project in projects:
            typer.echo(f"{project.id}  {project.name}  {project.status.value}")


@project_app.command("create")
@async_command
async def create_project(name: str, description: str | None = None) -> None:
    """Create a project."""
    async with cli_container() as container:
        project = Project(name=name, description=description)
        created = await container.repositories.projects.create(project)
        typer.echo(f"created {created.id}  {created.name}")


@project_app.command("show")
@async_command
async def show_project(project_id: str) -> None:
    """Show a project's state."""
    import uuid

    from brain.domain.identity import ProjectId

    async with cli_container() as container:
        project = await container.repositories.projects.get(ProjectId(uuid.UUID(project_id)))
        if project is None:
            typer.echo("not found")
            raise typer.Exit(code=1)
        typer.echo(f"id: {project.id}")
        typer.echo(f"name: {project.name}")
        typer.echo(f"status: {project.status.value}")
        typer.echo(f"repositories: {len(project.repositories)}")


@project_app.command("bootstrap")
@async_command
async def bootstrap(project_id: str, external_project_id: str) -> None:
    """Enqueue a bootstrap import of an existing OpenProject project."""
    import uuid

    from brain.domain.commands import BootstrapProjectCommand, CommandType, make_command
    from brain.domain.identity import ProjectId
    from brain.ports.commands import CommandQueue

    async with cli_container() as container:
        project = await container.repositories.projects.get(ProjectId(uuid.UUID(project_id)))
        if project is None:
            typer.echo("project not found")
            raise typer.Exit(code=1)
        queue = container.services["command_queue"]
        assert isinstance(queue, CommandQueue)
        await queue.enqueue(
            make_command(
                CommandType.BOOTSTRAP_PROJECT,
                BootstrapProjectCommand(
                    project_id=project.id,
                    external_project_id=external_project_id,
                ),
            )
        )
        typer.echo("bootstrap queued")


__all__ = ["project_app"]
