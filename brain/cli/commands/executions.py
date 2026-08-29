"""Execution and verification commands: show, diff, verify (Phase 30.7)."""

from __future__ import annotations

import uuid

import typer

from brain.cli.helpers import async_command, cli_container
from brain.domain.identity import ExecutionId, WorkItemId

execution_app = typer.Typer(help="Execution and verification operations.")


@execution_app.command("show")
@async_command
async def show(execution_id: str) -> None:
    """Show an execution's state."""
    async with cli_container() as container:
        execution = await container.repositories.executions.get(
            ExecutionId(uuid.UUID(execution_id))
        )
        if execution is None:
            typer.echo("not found")
            raise typer.Exit(code=1)
        typer.echo(f"id: {execution.id}")
        typer.echo(f"work item: {execution.work_item_id}")
        typer.echo(f"status: {execution.status.value}")
        typer.echo(f"started: {execution.started_at.isoformat()}")
        if execution.completed_at:
            typer.echo(f"completed: {execution.completed_at.isoformat()}")


@execution_app.command("diff")
@async_command
async def diff(execution_id: str) -> None:
    """Show an execution's diff (Milestone 1: unavailable)."""
    del execution_id
    typer.echo("diff unavailable (no source-control provider configured)")


@execution_app.command("verify")
@async_command
async def verify(execution_id: str, work_item_id: str) -> None:
    """Run verification for an execution."""
    async with cli_container() as container:
        outcome = await container.verification.verify(
            execution_id=ExecutionId(uuid.UUID(execution_id)),
            work_item_id=WorkItemId(uuid.UUID(work_item_id)),
            acceptance_criteria=[],
            changed_files=[],
        )
        typer.echo(f"verdict: {outcome.run.verdict.value}")
        typer.echo(f"pr allowed: {outcome.pr_readiness.pr_allowed}")
        for issue in outcome.run.issues:
            typer.echo(f"  - {issue}")


__all__ = ["execution_app"]
