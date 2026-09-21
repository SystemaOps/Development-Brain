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
    """Create a brand-new project ecosystem (brain + external systems)."""
    from brain.application.provisioning import ProjectProvisioningService

    async with cli_container() as container:
        service = container.services.get("project_provisioning")
        if service is None or not isinstance(service, ProjectProvisioningService):
            # Fallback: canonical project only when provisioning is not wired.
            project = await container.repositories.projects.create(
                Project(name=name, description=description)
            )
            typer.echo(f"created {project.id}  {project.name}")
            typer.echo("external systems: provisioning not configured")
            return
        result = await service.create_connected(name, description)
        project = result.project
        typer.echo(f"created {project.id}  {project.name}")
        for ref in result.refs_added:
            typer.echo(f"  linked {ref.provider}/{ref.external_type} {ref.external_id}")
        for detail in result.details:
            if detail.startswith(("work management", "source control", "documentation")):
                typer.echo(f"  {detail}")


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
async def bootstrap(
    project_id: str,
    external_project_id: str | None = typer.Argument(None, help="legacy alias for --openproject"),
    openproject: str | None = None,
    gitlab: str | None = None,
    xwiki: str | None = None,
) -> None:
    """Connect existing external projects and import their history.

    The legacy positional form ``bootstrap <project-id> <external-project-id>``
    is kept as an alias for ``--openproject``.
    """
    import uuid

    from brain.application.provisioning import ProjectProvisioningService
    from brain.domain.commands import BootstrapProjectCommand, CommandType, make_command
    from brain.domain.identity import ProjectId
    from brain.ports.commands import CommandQueue
    from brain.ports.provisioning import ExternalProjects

    op_id = openproject or external_project_id
    async with cli_container() as container:
        project = await container.repositories.projects.get(ProjectId(uuid.UUID(project_id)))
        if project is None:
            typer.echo("project not found")
            raise typer.Exit(code=1)

        service = container.services.get("project_provisioning")
        if service is not None and isinstance(service, ProjectProvisioningService):
            result = await service.bootstrap(
                project.id,
                ExternalProjects(
                    work_management=op_id,
                    source_control=gitlab,
                    documentation=xwiki,
                ),
            )
            for ref in result.refs_added:
                typer.echo(f"  linked {ref.provider}/{ref.external_type} {ref.external_id}")
            for detail in result.details:
                typer.echo(f"  {detail}")

        if op_id:
            queue = container.services["command_queue"]
            assert isinstance(queue, CommandQueue)
            await queue.enqueue(
                make_command(
                    CommandType.BOOTSTRAP_PROJECT,
                    BootstrapProjectCommand(
                        project_id=project.id,
                        external_project_id=op_id,
                    ),
                )
            )
            typer.echo("bootstrap queued (OpenProject historical import)")


__all__ = ["project_app"]
