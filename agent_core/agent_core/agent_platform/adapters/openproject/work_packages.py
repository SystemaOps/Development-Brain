from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from agent_core.application.openproject_mapping import (
    OpenProjectResourceCatalog,
)
from agent_core.ports.openproject import OpenProjectPort


class WorkPackageGateway(OpenProjectPort):
    """Platform-facing OpenProject gateway for work package synchronization."""


_ResultT = TypeVar("_ResultT")


class ManagedWorkPackageGateway:
    """Creates and closes a concrete OpenProject client around each gateway call."""

    def __init__(self, client_factory: Callable[[], OpenProjectPort]) -> None:
        self.client_factory = client_factory

    async def load_resource_catalog(self) -> OpenProjectResourceCatalog:
        return await self._call(lambda client: client.load_resource_catalog())

    async def get_work_package(self, work_package_id: str) -> dict[str, Any]:
        return await self._call(lambda client: client.get_work_package(work_package_id))

    async def list_work_package_activities(
        self,
        work_package_id: str,
    ) -> dict[str, Any]:
        return await self._call(
            lambda client: client.list_work_package_activities(work_package_id)
        )

    async def create_or_update_work_package(
        self,
        *,
        project_id: str,
        external_idempotency_key: str,
        payload: dict[str, Any],
        local_project_id: UUID | None = None,
        node_identity_id: UUID | None = None,
    ) -> dict[str, Any]:
        return await self._call(
            lambda client: client.create_or_update_work_package(
                project_id=project_id,
                external_idempotency_key=external_idempotency_key,
                payload=payload,
                local_project_id=local_project_id,
                node_identity_id=node_identity_id,
            )
        )

    async def add_comment(
        self,
        *,
        work_package_id: str,
        external_idempotency_key: str,
        markdown: str,
        local_project_id: UUID | None = None,
        node_identity_id: UUID | None = None,
    ) -> dict[str, Any]:
        return await self._call(
            lambda client: client.add_comment(
                work_package_id=work_package_id,
                external_idempotency_key=external_idempotency_key,
                markdown=markdown,
                local_project_id=local_project_id,
                node_identity_id=node_identity_id,
            )
        )

    async def _call(
        self,
        operation: Callable[[OpenProjectPort], Awaitable[_ResultT]],
    ) -> _ResultT:
        client = self.client_factory()
        try:
            return await operation(client)
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                await close()


__all__ = ["ManagedWorkPackageGateway", "WorkPackageGateway"]
