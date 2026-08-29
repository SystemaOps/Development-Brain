"""Repository commands: add, sync, ingest, status (Phase 30.4)."""

from __future__ import annotations

import uuid

import typer

from brain.cli.helpers import async_command, cli_container
from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.repositories import Repository

repository_app = typer.Typer(help="Repository operations.")


@repository_app.command("add")
@async_command
async def add(project_id: str, name: str, clone_url: str) -> None:
    """Register a repository in a project."""
    async with cli_container() as container:
        project = await container.repositories.projects.get(ProjectId(uuid.UUID(project_id)))
        if project is None:
            typer.echo("project not found")
            raise typer.Exit(code=1)
        repository = Repository(project_id=project.id, name=name, clone_url=clone_url)
        created = await container.repositories.repositories.create(repository)
        project.repositories.append(repository.id)
        await container.repositories.projects.update(project)
        typer.echo(f"registered {created.id}  {created.name}")


@repository_app.command("sync")
@async_command
async def sync(repository_id: str) -> None:
    """Enqueue a repository sync command."""
    from brain.domain.commands import CommandType, SyncRepositoryCommand, make_command
    from brain.ports.commands import CommandQueue

    async with cli_container() as container:
        queue = container.services["command_queue"]
        assert isinstance(queue, CommandQueue)
        await queue.enqueue(
            make_command(
                CommandType.SYNC_REPOSITORY,
                SyncRepositoryCommand(repository_id=RepositoryId(uuid.UUID(repository_id))),
            )
        )
        typer.echo("sync queued")


@repository_app.command("ingest")
@async_command
async def ingest(repository_id: str) -> None:
    """Enqueue a repository ingest command."""
    from brain.domain.commands import CommandType, IngestRepositoryCommand, make_command
    from brain.ports.commands import CommandQueue

    async with cli_container() as container:
        queue = container.services["command_queue"]
        assert isinstance(queue, CommandQueue)
        await queue.enqueue(
            make_command(
                CommandType.INGEST_REPOSITORY,
                IngestRepositoryCommand(repository_id=RepositoryId(uuid.UUID(repository_id))),
            )
        )
        typer.echo("ingest queued")


@repository_app.command("status")
@async_command
async def status(repository_id: str) -> None:
    """Show repository state."""
    async with cli_container() as container:
        repository = await container.repositories.repositories.get(
            RepositoryId(uuid.UUID(repository_id))
        )
        if repository is None:
            typer.echo("not found")
            raise typer.Exit(code=1)
        typer.echo(f"id: {repository.id}")
        typer.echo(f"name: {repository.name}")
        typer.echo(f"default branch: {repository.default_branch}")
        typer.echo(f"current revision: {repository.current_revision or '-'}")


__all__ = ["repository_app"]
