"""Context commands: build, show, explain (Phase 30.5)."""

from __future__ import annotations

import uuid

import typer

from brain.cli.helpers import async_command, cli_container
from brain.domain.context import ContextRequest
from brain.domain.identity import ContextCapsuleId, WorkItemId

context_app = typer.Typer(help="Context capsule operations.")


@context_app.command("build")
@async_command
async def build(
    work_item_id: str,
    budget: int = typer.Option(8000, help="Preferred token budget"),
) -> None:
    """Build a context capsule for a work item."""
    async with cli_container() as container:
        work_item = await container.repositories.work_items.get(WorkItemId(uuid.UUID(work_item_id)))
        if work_item is None:
            typer.echo("work item not found")
            raise typer.Exit(code=1)
        request = ContextRequest(
            work_item_id=work_item.id,
            project_id=work_item.project_id,
            preferred_token_budget=budget,
        )
        result = await container.context_engine.build(request)
        typer.echo(f"capsule {result.capsule.id}")
        typer.echo(f"tokens {result.capsule.total_tokens}/{result.capsule.model_budget_tokens}")
        typer.echo(f"candidates {result.candidates_included}/{result.candidates_gathered}")


@context_app.command("show")
@async_command
async def show(capsule_id: str) -> None:
    """Show a context capsule."""
    async with cli_container() as container:
        capsule = await container.repositories.context_capsules.get_capsule(
            ContextCapsuleId(uuid.UUID(capsule_id))
        )
        if capsule is None:
            typer.echo("not found")
            raise typer.Exit(code=1)
        typer.echo(f"id: {capsule.id}")
        typer.echo(f"work item: {capsule.work_item_id}")
        typer.echo(f"type: {capsule.context_type.value}")
        typer.echo(f"tokens: {capsule.total_tokens}")
        typer.echo(f"candidates: {len(capsule.candidates)}")


@context_app.command("explain")
@async_command
async def explain(capsule_id: str) -> None:
    """Explain why each context item was selected."""
    async with cli_container() as container:
        capsule = await container.repositories.context_capsules.get_capsule(
            ContextCapsuleId(uuid.UUID(capsule_id))
        )
        if capsule is None:
            typer.echo("not found")
            raise typer.Exit(code=1)
        for candidate in capsule.candidates:
            typer.echo(
                f"- {candidate.entity_type} {candidate.entity_id} "
                f"[{candidate.retrieval_source.value} {candidate.relevance_score:.2f}] "
                f"{candidate.reason}"
            )


__all__ = ["context_app"]
