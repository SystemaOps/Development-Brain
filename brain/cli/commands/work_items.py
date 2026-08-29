"""Work item commands: create, show, run, retry (Phase 30.6)."""

from __future__ import annotations

import uuid

import typer

from brain.cli.helpers import async_command, cli_container
from brain.domain.identity import ProjectId, WorkItemId
from brain.domain.work_items import WorkItem

work_item_app = typer.Typer(help="Work item operations.")


@work_item_app.command("create")
@async_command
async def create(project_id: str, title: str, description: str = "") -> None:
    """Create an internal work item."""
    async with cli_container() as container:
        work_item = WorkItem(
            project_id=ProjectId(uuid.UUID(project_id)),
            title=title,
            description=description,
        )
        created = await container.repositories.work_items.create(work_item)
        typer.echo(f"created {created.id}  {created.title}")


@work_item_app.command("show")
@async_command
async def show(work_item_id: str) -> None:
    """Show a work item's state."""
    async with cli_container() as container:
        work_item = await container.repositories.work_items.get(WorkItemId(uuid.UUID(work_item_id)))
        if work_item is None:
            typer.echo("not found")
            raise typer.Exit(code=1)
        typer.echo(f"id: {work_item.id}")
        typer.echo(f"title: {work_item.title}")
        typer.echo(f"human status: {work_item.human_work_status.value}")
        typer.echo(f"implementation: {work_item.implementation_status.value}")
        typer.echo(f"verification: {work_item.verification_status.value}")
        typer.echo(f"pr: {work_item.pull_request_status.value}")


@work_item_app.command("run")
@async_command
async def run(work_item_id: str) -> None:
    """Enqueue the RunWorkItem command for a work item."""
    from brain.domain.commands import CommandType, RunWorkItemCommand, make_command
    from brain.ports.commands import CommandQueue

    async with cli_container() as container:
        work_item = await container.repositories.work_items.get(WorkItemId(uuid.UUID(work_item_id)))
        if work_item is None:
            typer.echo("not found")
            raise typer.Exit(code=1)
        queue = container.services["command_queue"]
        assert isinstance(queue, CommandQueue)
        await queue.enqueue(
            make_command(
                CommandType.RUN_WORK_ITEM,
                RunWorkItemCommand(work_item_id=work_item.id),
            )
        )
        typer.echo("run queued")


@work_item_app.command("retry")
@async_command
async def retry(work_item_id: str) -> None:
    """Enqueue the ExecuteWorkItem command (retry) for a work item."""
    from brain.domain.commands import CommandType, ExecuteWorkItemCommand, make_command
    from brain.ports.commands import CommandQueue

    async with cli_container() as container:
        work_item = await container.repositories.work_items.get(WorkItemId(uuid.UUID(work_item_id)))
        if work_item is None:
            typer.echo("not found")
            raise typer.Exit(code=1)
        queue = container.services["command_queue"]
        assert isinstance(queue, CommandQueue)
        await queue.enqueue(
            make_command(
                CommandType.EXECUTE_WORK_ITEM,
                ExecuteWorkItemCommand(work_item_id=work_item.id),
            )
        )
        typer.echo("retry queued")


__all__ = ["work_item_app"]
