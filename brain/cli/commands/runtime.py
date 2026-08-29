"""Runtime commands: status, health, capabilities (Phase 30.2)."""

from __future__ import annotations

import typer

from brain.cli.helpers import async_command, cli_container

runtime_app = typer.Typer(help="Runtime status and health.")


def _print_capability(name: str, status: str) -> None:
    typer.echo(f"{name:<24} {status}")


@runtime_app.command("status")
@async_command
async def status() -> None:
    """Show runtime status: readiness, executors, capabilities."""
    async with cli_container() as container:
        typer.echo(f"environment: {container.settings.runtime.environment}")
        typer.echo(f"ready: {container.is_ready()}")
        if container.ready_problems():
            typer.echo("problems:")
            for problem in container.ready_problems():
                typer.echo(f"  - {problem}")
        typer.echo(f"executors: {', '.join(d.name for d in container.executor_descriptors)}")


@runtime_app.command("health")
@async_command
async def health() -> None:
    """Show liveness and readiness."""
    async with cli_container() as container:
        if container.is_ready():
            typer.echo("ready")
        else:
            typer.echo("not_ready")
            for problem in container.ready_problems():
                typer.echo(f"  - {problem}")


@runtime_app.command("capabilities")
@async_command
async def capabilities() -> None:
    """List runtime capability states."""
    async with cli_container() as container:
        for name, descriptor in container.capability_registry().snapshot().items():
            _print_capability(name, descriptor.health.status.value)


__all__ = ["runtime_app"]
