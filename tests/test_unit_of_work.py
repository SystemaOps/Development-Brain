"""Unit of Work transaction boundary tests (Task 2.5)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from brain.adapters.postgresql.config import DatabaseSettings
from brain.adapters.postgresql.database import (
    async_session_factory,
    create_async_engine,
    create_repositories,
)
from brain.adapters.postgresql.tables import Base
from brain.adapters.postgresql.unit_of_work import PostgresUnitOfWork
from brain.domain.projects import Project
from brain.domain.repositories import Repository


@pytest.fixture
async def postgres_schema(postgres_engine: AsyncEngine) -> None:
    async with postgres_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def test_commit_persists_across_repositories(
    postgres_schema: None, postgres_engine: AsyncEngine
) -> None:
    factory = async_session_factory(postgres_engine)
    project = Project(name="atomic")
    repository = Repository(project_id=project.id, name="svc", clone_url="git@example:svc.git")

    async with PostgresUnitOfWork(factory) as uow:
        await uow.repos.projects.create(project)
        await uow.repos.repositories.create(repository)
        await uow.commit()

    async with factory() as session:
        repos = create_repositories(session)
        assert await repos.projects.get(project.id) == project
        assert await repos.repositories.get(repository.id) == repository

    async with PostgresUnitOfWork(factory) as uow:
        await uow.repos.repositories.delete(repository.id)
        await uow.repos.projects.delete(project.id)
        await uow.commit()


async def test_rollback_discards_uncommitted_work(
    postgres_schema: None, postgres_engine: AsyncEngine
) -> None:
    factory = async_session_factory(postgres_engine)
    project = Project(name="rolled-back")

    async with PostgresUnitOfWork(factory) as uow:
        await uow.repos.projects.create(project)

    async with factory() as session:
        assert await create_repositories(session).projects.get(project.id) is None


async def test_exception_rolls_back_entire_transaction(
    postgres_schema: None, postgres_engine: AsyncEngine
) -> None:
    factory = async_session_factory(postgres_engine)
    project = Project(name="boom")
    repository = Repository(project_id=project.id, name="svc", clone_url="git@example:svc.git")

    with pytest.raises(RuntimeError):
        async with PostgresUnitOfWork(factory) as uow:
            await uow.repos.projects.create(project)
            await uow.repos.repositories.create(repository)
            raise RuntimeError("pipeline failed")

    async with factory() as session:
        repos = create_repositories(session)
        assert await repos.projects.get(project.id) is None
        assert await repos.repositories.get(repository.id) is None


async def test_uow_not_active_rejects_commit(postgres_settings: DatabaseSettings) -> None:
    engine = create_async_engine(postgres_settings)
    uow = PostgresUnitOfWork(async_session_factory(engine))
    with pytest.raises(RuntimeError):
        await uow.commit()


async def test_external_reference_rows_commit_atomically(
    postgres_schema: None, postgres_engine: AsyncEngine
) -> None:
    from sqlalchemy import select

    from brain.adapters.postgresql.tables import ExternalReferenceRow
    from brain.domain.external_reference import ExternalReference

    factory = async_session_factory(postgres_engine)
    project = Project(
        name="refs",
        external_refs=[ExternalReference(provider="jira", external_id="AUTH-1")],
    )

    async with PostgresUnitOfWork(factory) as uow:
        await uow.repos.projects.create(project)
        await uow.commit()

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(ExternalReferenceRow).where(ExternalReferenceRow.owner_id == project.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async with PostgresUnitOfWork(factory) as uow:
        await uow.repos.projects.delete(project.id)
        await uow.commit()
