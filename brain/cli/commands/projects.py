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


@project_app.command("delete")
@async_command
async def delete_project(
    project_id: str, yes: bool = typer.Option(False, "--yes", "-y", help="skip confirmation")
) -> None:
    """Delete a project and its imported state (cascade).

    Removes the canonical project plus linked work items, comments,
    attachments, relations, provider mappings/snapshots, sync watermarks and
    bootstrap state.  External systems (OpenProject/GitLab/XWiki) are NOT
    touched.
    """
    import uuid

    from sqlalchemy import delete as sql_delete

    from brain.domain.identity import ProjectId

    async with cli_container() as container:
        project = await container.repositories.projects.get(ProjectId(uuid.UUID(project_id)))
        if project is None:
            typer.echo("project not found")
            raise typer.Exit(code=1)
        if not yes:
            confirm = typer.confirm(
                f"Delete project {project.name!r} ({project.id}) and all its imported state?"
            )
            if not confirm:
                typer.echo("aborted")
                return

        session = container.session
        if session is None:
            typer.echo("no database session available")
            raise typer.Exit(code=1)

        from brain.adapters.postgresql.tables import (
            AttachmentRow,
            CommentRow,
            DocumentNodeRow,
            DocumentRow,
            DocumentVersionRow,
            ExternalReferenceRow,
            OpenProjectSnapshotRow,
            ProviderBootstrapStateRow,
            ProviderSyncWatermarkRow,
            SyncConflictRow,
            WorkItemRelationRow,
            WorkManagementMappingRow,
        )

        # Cascade documents (and their versions/nodes) into the deletion.
        document_ids = [
            d.id for d in await container.repositories.documents.list_by_project(project.id)
        ]
        if document_ids:
            version_ids = [
                v.id
                for document_id in document_ids
                for v in await container.repositories.documents.list_versions(document_id)
            ]
            if version_ids:
                await session.execute(
                    sql_delete(DocumentNodeRow).where(DocumentNodeRow.version_id.in_(version_ids))
                )
                await session.execute(
                    sql_delete(DocumentVersionRow).where(DocumentVersionRow.id.in_(version_ids))
                )
            await session.execute(sql_delete(DocumentRow).where(DocumentRow.id.in_(document_ids)))

        provider_external_ids = [
            ref.external_id
            for ref in project.external_refs
            if ref.provider == "openproject" and ref.external_type == "project"
        ]

        work_items = await container.repositories.work_items.list_by_project(project.id)
        work_item_ids = [w.id for w in work_items]
        work_item_external_ids = [
            ref.external_id
            for w in work_items
            for ref in w.external_refs
            if ref.provider == "openproject" and ref.external_type == "work_package"
        ]

        for table, column in (
            (CommentRow, "work_item_id"),
            (AttachmentRow, "work_item_id"),
            (WorkItemRelationRow, "source_work_item_id"),
            (WorkManagementMappingRow, "work_item_id"),
            (SyncConflictRow, "work_item_id"),
        ):
            await session.execute(
                sql_delete(table).where(getattr(table, column).in_(work_item_ids))
            )
        if work_item_external_ids:
            await session.execute(
                sql_delete(OpenProjectSnapshotRow).where(
                    OpenProjectSnapshotRow.external_id.in_(work_item_external_ids)
                )
            )
        for work_item_id in work_item_ids:
            await container.repositories.work_items.delete(work_item_id)
        await session.execute(
            sql_delete(ExternalReferenceRow).where(
                ExternalReferenceRow.owner_type == "work_item",
                ExternalReferenceRow.owner_id.in_(work_item_ids),
            )
        )
        if provider_external_ids:
            await session.execute(
                sql_delete(ProviderSyncWatermarkRow).where(
                    ProviderSyncWatermarkRow.sync_key.in_(
                        f"work_items:{external_id}" for external_id in provider_external_ids
                    )
                )
            )
        await session.execute(
            sql_delete(ProviderBootstrapStateRow).where(
                ProviderBootstrapStateRow.project_id == project.id
            )
        )
        await container.repositories.projects.delete(project.id)
        typer.echo(
            f"deleted {project.name} ({len(work_items)} work items, "
            f"{len(work_item_external_ids)} snapshots removed)"
        )


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
