from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx

from agent_core.application.openproject_feedback import (
    has_openproject_idempotency_marker,
    markdown_with_idempotency_marker,
    openproject_idempotency_marker,
)
from agent_core.application.openproject_mapping import OpenProjectResourceCatalog
from agent_core.application.openproject_reconciliation import (
    detect_human_edit_summary,
)
from agent_core.config import settings
from agent_core.ports.openproject import (
    OpenProjectArtifactMapping,
    OpenProjectArtifactStorePort,
    OpenProjectOperationClaim,
    OpenProjectOperationStatus,
    OpenProjectOperationType,
    OpenProjectOutboundStorePort,
    OpenProjectReconciliationStorePort,
)

__all__ = [
    "OpenProjectClient",
    "has_openproject_idempotency_marker",
    "markdown_with_idempotency_marker",
    "openproject_idempotency_marker",
    "resolve_openproject_api_token",
]


def resolve_openproject_api_token(
    *,
    api_key: str | None = None,
    api_token_file: str | None = None,
) -> str:
    if api_token_file and api_token_file.strip():
        token_path = Path(api_token_file)
        if token_path.exists():
            return token_path.read_text(encoding="utf-8").strip()

    if api_key and api_key.strip():
        return api_key.strip()

    return ""


def _api_path_from_href(href: str) -> str:
    parsed = urlparse(href)
    path = parsed.path if parsed.scheme else href
    if path.startswith("/api/v3"):
        path = path.removeprefix("/api/v3")
    return path or "/"


class OpenProjectClient:
    def __init__(
        self,
        *,
        artifact_store: OpenProjectArtifactStorePort | None = None,
        outbound_store: OpenProjectOutboundStorePort | None = None,
        reconciliation_store: OpenProjectReconciliationStorePort | None = None,
        http_client: Any | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        api_token_file: str | None = None,
        request_timeout_seconds: int | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self.outbound_store = outbound_store
        self.reconciliation_store = reconciliation_store
        self._owns_client = http_client is None
        if http_client is not None:
            self.client = http_client
            return

        token = resolve_openproject_api_token(
            api_key=api_key if api_key is not None else settings.openproject_api_key,
            api_token_file=(
                api_token_file
                if api_token_file is not None
                else settings.openproject_api_token_file
            ),
        )
        self.client = httpx.AsyncClient(
            base_url=f"{(base_url or settings.openproject_base_url).rstrip('/')}/api/v3",
            auth=("apikey", token),
            headers={
                "Accept": "application/hal+json",
                "Content-Type": "application/json",
            },
            timeout=request_timeout_seconds or settings.openproject_request_timeout_seconds,
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    async def create_project(
        self,
        identifier: str,
        name: str,
        description: str,
        *,
        local_project_id: UUID | None = None,
    ) -> dict[str, Any]:
        response = await self.request(
            "POST",
            "/projects",
            json={
                "identifier": identifier,
                "name": name,
                "description": {"format": "markdown", "raw": description},
            },
        )
        await self._record_openproject_artifact_mapping(
            local_project_id=local_project_id,
            artifact_type="project",
            payload=response,
            fallback_external_id=identifier,
        )
        return response

    async def list_types(self) -> dict[str, str]:
        data = await self.request("GET", "/types")
        return _hal_elements_by_name(data)

    async def list_statuses(self) -> dict[str, str]:
        data = await self.request("GET", "/statuses")
        return _hal_elements_by_name(data)

    async def list_priorities(self) -> dict[str, str]:
        data = await self.request("GET", "/priorities")
        return _hal_elements_by_name(data)

    async def load_resource_catalog(self) -> OpenProjectResourceCatalog:
        return OpenProjectResourceCatalog(
            type_hrefs=await self.list_types(),
            status_hrefs=await self.list_statuses(),
            priority_hrefs=await self.list_priorities(),
        )

    async def get_work_package(self, work_package_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/work_packages/{work_package_id}")

    async def list_work_package_activities(self, work_package_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/work_packages/{work_package_id}/activities")

    async def create_or_update_work_package(
        self,
        *,
        project_id: str,
        external_idempotency_key: str,
        payload: dict[str, Any],
        local_project_id: UUID | None = None,
        node_identity_id: UUID | None = None,
    ) -> dict[str, Any]:
        store = self._require_outbound_store()
        target_external_id = _work_package_id_from_payload(payload)
        claim = await store.claim_operation(
            idempotency_key=external_idempotency_key,
            operation_type=OpenProjectOperationType.CREATE_OR_UPDATE_WORK_PACKAGE,
            request_payload={"project_id": project_id, "payload": payload},
            project_id=local_project_id,
            target_artifact_type="work_package",
            target_external_id=target_external_id,
        )
        if not claim.should_execute:
            if claim.response_payload is not None:
                await self._record_work_package_mapping(
                    local_project_id=local_project_id,
                    node_identity_id=node_identity_id,
                    payload=claim.response_payload,
                    fallback_external_id=target_external_id,
                )
            return _skipped_response(claim)

        try:
            if target_external_id:
                before_payload = await self.get_work_package(target_external_id)
                artifact_mapping = await self._record_work_package_mapping(
                    local_project_id=local_project_id,
                    node_identity_id=node_identity_id,
                    payload=before_payload,
                    fallback_external_id=target_external_id,
                )
                before_activities_payload = await self.list_work_package_activities(
                    target_external_id
                )
                await self._record_reconciliation_snapshot(
                    outbound_idempotency_key=external_idempotency_key,
                    operation_type=OpenProjectOperationType.CREATE_OR_UPDATE_WORK_PACKAGE,
                    target_artifact_type="work_package",
                    target_external_id=target_external_id,
                    before_payload=before_payload,
                    before_activities_payload=before_activities_payload,
                    agent_payload=payload,
                    project_id=local_project_id,
                    artifact_id=(
                        artifact_mapping.artifact_id if artifact_mapping else None
                    ),
                )
                update_payload = payload
                if (
                    "lockVersion" not in update_payload
                    and before_payload.get("lockVersion") is not None
                ):
                    update_payload = {
                        **update_payload,
                        "lockVersion": before_payload["lockVersion"],
                    }
                response = await self.request(
                    "PATCH",
                    f"/work_packages/{target_external_id}",
                    json=update_payload,
                )
            else:
                response = await self.request(
                    "POST",
                    f"/projects/{project_id}/work_packages",
                    json=payload,
                )
        except Exception as exc:
            await store.mark_failed(
                idempotency_key=external_idempotency_key,
                error_message=str(exc),
            )
            raise

        await store.mark_succeeded(
            idempotency_key=external_idempotency_key,
            response_payload=response,
        )
        await self._record_work_package_mapping(
            local_project_id=local_project_id,
            node_identity_id=node_identity_id,
            payload=response,
            fallback_external_id=target_external_id,
        )
        return response

    async def add_comment(
        self,
        *,
        work_package_id: str,
        external_idempotency_key: str,
        markdown: str,
        local_project_id: UUID | None = None,
        node_identity_id: UUID | None = None,
    ) -> dict[str, Any]:
        store = self._require_outbound_store()
        marked_markdown = markdown_with_idempotency_marker(
            markdown,
            external_idempotency_key,
        )
        claim = await store.claim_operation(
            idempotency_key=external_idempotency_key,
            operation_type=OpenProjectOperationType.ADD_COMMENT,
            request_payload={
                "work_package_id": work_package_id,
                "markdown": marked_markdown,
            },
            project_id=local_project_id,
            target_artifact_type="work_package",
            target_external_id=work_package_id,
        )
        if not claim.should_execute:
            return _skipped_response(claim)

        try:
            work_package = await self.get_work_package(work_package_id)
            artifact_mapping = await self._record_work_package_mapping(
                local_project_id=local_project_id,
                node_identity_id=node_identity_id,
                payload=work_package,
                fallback_external_id=work_package_id,
            )
            before_activities_payload = None
            if claim.reclaimed:
                before_activities_payload = await self.list_work_package_activities(
                    work_package_id
                )
                existing_activity = _find_idempotent_activity(
                    before_activities_payload,
                    external_idempotency_key,
                )
                if existing_activity is not None:
                    await store.mark_succeeded(
                        idempotency_key=external_idempotency_key,
                        response_payload=existing_activity,
                    )
                    return existing_activity
            await self._record_reconciliation_snapshot(
                outbound_idempotency_key=external_idempotency_key,
                operation_type=OpenProjectOperationType.ADD_COMMENT,
                target_artifact_type="work_package",
                target_external_id=work_package_id,
                before_payload=work_package,
                agent_payload={
                    "comment": {
                        "raw": marked_markdown,
                    }
                },
                before_activities_payload=before_activities_payload,
                project_id=local_project_id,
                artifact_id=(
                    artifact_mapping.artifact_id if artifact_mapping else None
                ),
            )
            add_comment_href = (
                work_package.get("_links", {})
                .get("addComment", {})
                .get("href")
            )
            if not add_comment_href:
                raise RuntimeError("The bot cannot add a comment to this work package.")

            response = await self.request(
                "POST",
                _api_path_from_href(add_comment_href),
                json={"comment": {"raw": marked_markdown}},
            )
        except Exception as exc:
            await store.mark_failed(
                idempotency_key=external_idempotency_key,
                error_message=str(exc),
            )
            raise

        await store.mark_succeeded(
            idempotency_key=external_idempotency_key,
            response_payload=response,
        )
        return response

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def _require_outbound_store(self) -> OpenProjectOutboundStorePort:
        if self.outbound_store is None:
            raise RuntimeError(
                "OpenProject outbound_store is required for idempotent mutations"
            )
        return self.outbound_store

    async def _record_reconciliation_snapshot(
        self,
        *,
        outbound_idempotency_key: str,
        operation_type: OpenProjectOperationType,
        target_artifact_type: str,
        target_external_id: str,
        before_payload: dict[str, Any],
        agent_payload: dict[str, Any],
        before_activities_payload: dict[str, Any] | None = None,
        project_id: UUID | None = None,
        artifact_id: UUID | None = None,
    ) -> None:
        if self.reconciliation_store is None:
            return
        await self.reconciliation_store.record_snapshot(
            outbound_idempotency_key=outbound_idempotency_key,
            operation_type=operation_type,
            target_artifact_type=target_artifact_type,
            target_external_id=target_external_id,
            before_payload=before_payload,
            before_activities_payload=before_activities_payload,
            agent_payload=agent_payload,
            project_id=project_id,
            artifact_id=artifact_id,
            detected_human_edits=detect_human_edit_summary(
                before_payload=before_payload,
                agent_payload=agent_payload,
            ),
        )

    async def _record_work_package_mapping(
        self,
        *,
        local_project_id: UUID | None,
        payload: dict[str, Any],
        node_identity_id: UUID | None = None,
        fallback_external_id: str | None = None,
    ) -> OpenProjectArtifactMapping | None:
        return await self._record_openproject_artifact_mapping(
            local_project_id=local_project_id,
            artifact_type="work_package",
            payload=payload,
            node_identity_id=node_identity_id,
            fallback_external_id=fallback_external_id,
        )

    async def _record_openproject_artifact_mapping(
        self,
        *,
        local_project_id: UUID | None,
        artifact_type: str,
        payload: dict[str, Any],
        node_identity_id: UUID | None = None,
        fallback_external_id: str | None = None,
    ) -> OpenProjectArtifactMapping | None:
        if self.artifact_store is None or local_project_id is None:
            return None

        external_id = _external_id_from_payload(
            payload,
            fallback_external_id=fallback_external_id,
        )
        if external_id is None:
            raise RuntimeError(
                f"OpenProject {artifact_type} response did not include an external id"
            )

        return await self.artifact_store.upsert_mapping(
            project_id=local_project_id,
            node_identity_id=node_identity_id,
            artifact_type=artifact_type,
            external_id=external_id,
            external_url=_self_href_from_payload(payload),
            external_payload=payload,
        )


def _work_package_id_from_payload(payload: dict[str, Any]) -> str | None:
    value = payload.get("id") or payload.get("work_package_id")
    if value is None:
        return None
    return str(value)


def _external_id_from_payload(
    payload: dict[str, Any],
    *,
    fallback_external_id: str | None = None,
) -> str | None:
    value = payload.get("id") or payload.get("work_package_id")
    if value is not None:
        return str(value)

    self_href = _self_href_from_payload(payload)
    if self_href:
        parsed_id = _last_path_segment(self_href)
        if parsed_id:
            return parsed_id

    return fallback_external_id


def _self_href_from_payload(payload: dict[str, Any]) -> str | None:
    self_link = payload.get("_links", {}).get("self")
    if isinstance(self_link, dict):
        href = self_link.get("href")
        return str(href) if href is not None else None
    return None


def _last_path_segment(href: str) -> str | None:
    path = urlparse(href).path
    segment = path.rstrip("/").rsplit("/", 1)[-1]
    return segment or None


def _find_idempotent_activity(
    activities_payload: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any] | None:
    activities = activities_payload.get("_embedded", {}).get("elements", [])
    for activity in activities:
        comment = activity.get("comment")
        comment_payload = comment if isinstance(comment, dict) else {}
        texts = (
            comment_payload.get("raw"),
            comment_payload.get("html"),
            activity.get("raw"),
        )
        if any(
            isinstance(text, str)
            and has_openproject_idempotency_marker(text, idempotency_key)
            for text in texts
        ):
            return activity
    return None


def _hal_elements_by_name(data: dict[str, Any]) -> dict[str, str]:
    elements = data.get("_embedded", {}).get("elements", [])
    return {
        item["name"].strip(): item["_links"]["self"]["href"]
        for item in elements
        if item.get("name") and item.get("_links", {}).get("self", {}).get("href")
    }


def _skipped_response(claim: OpenProjectOperationClaim) -> dict[str, Any]:
    if claim.status == OpenProjectOperationStatus.SUCCEEDED and claim.response_payload is not None:
        return claim.response_payload
    return {
        "idempotency_key": claim.idempotency_key,
        "operation_type": claim.operation_type.value,
        "status": claim.status.value,
        "skipped": True,
        "error_message": claim.error_message,
    }
