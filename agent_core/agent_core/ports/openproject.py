from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from agent_core.application.openproject_mapping import (
        OpenProjectResourceCatalog,
    )


class OpenProjectOperationType(StrEnum):
    CREATE_OR_UPDATE_WORK_PACKAGE = "create_or_update_work_package"
    ADD_COMMENT = "add_comment"


class OpenProjectOperationStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class OpenProjectOperationClaim:
    idempotency_key: str
    operation_type: OpenProjectOperationType
    status: OpenProjectOperationStatus
    should_execute: bool
    response_payload: dict[str, Any] | None = None
    error_message: str | None = None
    reclaimed: bool = False


@dataclass(frozen=True)
class OpenProjectArtifactMapping:
    artifact_id: UUID
    project_id: UUID
    artifact_type: str
    external_id: str
    external_url: str | None = None
    external_payload: dict[str, Any] | None = None
    node_identity_id: UUID | None = None


class OpenProjectOutboundStorePort(Protocol):
    async def claim_operation(
        self,
        *,
        idempotency_key: str,
        operation_type: OpenProjectOperationType,
        request_payload: dict[str, Any],
        project_id: UUID | None = None,
        artifact_id: UUID | None = None,
        target_artifact_type: str | None = None,
        target_external_id: str | None = None,
    ) -> OpenProjectOperationClaim:
        ...

    async def mark_succeeded(
        self,
        *,
        idempotency_key: str,
        response_payload: dict[str, Any],
    ) -> None:
        ...

    async def mark_failed(
        self,
        *,
        idempotency_key: str,
        error_message: str,
    ) -> None:
        ...


class OpenProjectArtifactStorePort(Protocol):
    async def upsert_mapping(
        self,
        *,
        project_id: UUID,
        artifact_type: str,
        external_id: str,
        external_url: str | None = None,
        external_payload: dict[str, Any] | None = None,
        node_identity_id: UUID | None = None,
    ) -> OpenProjectArtifactMapping:
        ...


class OpenProjectReconciliationStorePort(Protocol):
    async def record_snapshot(
        self,
        *,
        outbound_idempotency_key: str,
        operation_type: OpenProjectOperationType,
        target_artifact_type: str,
        target_external_id: str,
        before_payload: dict[str, Any],
        agent_payload: dict[str, Any],
        before_activities_payload: dict[str, Any] | None = None,
        detected_human_edits: list[dict[str, Any]] | None = None,
        project_id: UUID | None = None,
        artifact_id: UUID | None = None,
    ) -> None:
        ...


class OpenProjectPort(Protocol):
    async def load_resource_catalog(self) -> "OpenProjectResourceCatalog":
        ...

    async def get_work_package(self, work_package_id: str) -> dict[str, Any]:
        ...

    async def list_work_package_activities(self, work_package_id: str) -> dict[str, Any]:
        ...

    async def create_or_update_work_package(
        self,
        *,
        project_id: str,
        external_idempotency_key: str,
        payload: dict[str, Any],
        local_project_id: UUID | None = None,
        node_identity_id: UUID | None = None,
    ) -> dict[str, Any]:
        ...

    async def add_comment(
        self,
        *,
        work_package_id: str,
        external_idempotency_key: str,
        markdown: str,
        local_project_id: UUID | None = None,
        node_identity_id: UUID | None = None,
    ) -> dict[str, Any]:
        ...
