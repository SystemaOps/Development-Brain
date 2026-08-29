"""Explicit transaction boundaries: the Unit of Work.

Repositories share a single :class:`sqlalchemy.ext.asyncio.AsyncSession`
inside a :class:`PostgresUnitOfWork`, so operations that touch several
canonical entities are atomic.  Example operations that must be atomic:

- create an execution and attach its context capsule;
- save a verification result and its evidence;
- ingest a document version and update the current-version pointer;
- sync an external work item and its external reference rows.
"""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from brain.adapters.postgresql.database import PostgresRepositories, SessionFactory


class PostgresUnitOfWork:
    """Transaction scope over a bundle of PostgreSQL repositories.

    Usage::

        async with PostgresUnitOfWork(session_factory) as uow:
            await uow.repos.projects.create(project)
            await uow.repos.repositories.create(repository)
            await uow.commit()

    ``commit`` persists the work; leaving the context manager without
    ``commit`` rolls everything back.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._repos: PostgresRepositories | None = None

    @property
    def repos(self) -> PostgresRepositories:
        if self._repos is None:
            raise RuntimeError("Unit of work is not active")
        return self._repos

    async def __aenter__(self) -> PostgresUnitOfWork:
        session = self._session_factory()
        self._session = session
        self._repos = PostgresRepositories(session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._session
        if session is None:
            return
        if exc_type is not None:
            await session.rollback()
        await session.close()
        self._session = None
        self._repos = None

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work is not active")
        await self._session.commit()

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work is not active")
        await self._session.rollback()
