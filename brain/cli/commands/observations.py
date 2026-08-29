"""Observation commands: list, show, acknowledge, resolve (Phase 30.8)."""

from __future__ import annotations

import uuid

import typer

from brain.cli.helpers import async_command, cli_container
from brain.domain.identity import ObservationId, ProjectId, WorkItemId

observation_app = typer.Typer(help="Engineering journal operations.")


@observation_app.command("list")
@async_command
async def list_observations(
    project_id: str | None = None,
    work_item_id: str | None = None,
) -> None:
    """List observations (optionally scoped to a project or work item)."""
    from brain.application.observations import ObservationService

    async with cli_container() as container:
        service = container.services["observations"]
        assert isinstance(service, ObservationService)
        if work_item_id:
            observations = await service.list_by_work_item(WorkItemId(uuid.UUID(work_item_id)))
        elif project_id:
            observations = await service.list_by_project(ProjectId(uuid.UUID(project_id)))
        else:
            observations = await service.list_recent()
        for observation in observations:
            typer.echo(
                f"{observation.id}  [{observation.observation_type.value}] "
                f"{observation.status.value}  {observation.title}"
            )


@observation_app.command("show")
@async_command
async def show(observation_id: str) -> None:
    """Show an observation's detail."""
    from brain.application.observations import ObservationService

    async with cli_container() as container:
        service = container.services["observations"]
        assert isinstance(service, ObservationService)
        observation = await service.get(ObservationId(uuid.UUID(observation_id)))
        if observation is None:
            typer.echo("not found")
            raise typer.Exit(code=1)
        typer.echo(f"id: {observation.id}")
        typer.echo(f"type: {observation.observation_type.value}")
        typer.echo(f"severity: {observation.severity.value}")
        typer.echo(f"visibility: {observation.visibility.value}")
        typer.echo(f"status: {observation.status.value}")
        typer.echo(f"title: {observation.title}")
        if observation.body:
            typer.echo(f"body: {observation.body}")


@observation_app.command("acknowledge")
@async_command
async def acknowledge(observation_id: str) -> None:
    """Acknowledge an observation."""
    from brain.application.observations import ObservationService

    async with cli_container() as container:
        service = container.services["observations"]
        assert isinstance(service, ObservationService)
        observation = await service.acknowledge(ObservationId(uuid.UUID(observation_id)))
        if observation is None:
            typer.echo("not found")
            raise typer.Exit(code=1)
        typer.echo("acknowledged")


@observation_app.command("resolve")
@async_command
async def resolve(observation_id: str) -> None:
    """Resolve an observation."""
    from brain.application.observations import ObservationService

    async with cli_container() as container:
        service = container.services["observations"]
        assert isinstance(service, ObservationService)
        observation = await service.resolve(ObservationId(uuid.UUID(observation_id)))
        if observation is None:
            typer.echo("not found")
            raise typer.Exit(code=1)
        typer.echo("resolved")


__all__ = ["observation_app"]
