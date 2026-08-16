"""Backstage software catalog adapter (Task 15.5).

Reads Backstage catalog entities (Domain, System, Component, API, Resource,
owner, dependencies) and maps them to the canonical software model.  The brain
never depends on Backstage; it is an optional enrichment source.
"""

from __future__ import annotations

from typing import Any, Protocol

from brain.domain.projects import Project
from brain.domain.software_model import (
    ComponentType,
    Interface,
    Resource,
    ResourceType,
    SoftwareComponent,
)
from brain.ports.software_catalog import SoftwareCatalogPort


class BackstageTransport(Protocol):
    """Minimal Backstage catalog REST surface."""

    async def list_entities(self, kind: str) -> list[dict[str, Any]]: ...


class BackstageCatalogAdapter(SoftwareCatalogPort):
    """SoftwareCatalogPort reading from Backstage catalog-info."""

    def __init__(self, transport: BackstageTransport) -> None:
        self._transport = transport

    async def list_components(self, project: Project) -> list[SoftwareComponent]:
        components: list[SoftwareComponent] = []
        for raw in await self._transport.list_entities("Component"):
            name = str(raw.get("metadata", {}).get("name") or raw.get("name") or "")
            spec = raw.get("spec", {})
            components.append(
                SoftwareComponent(
                    project_id=project.id,
                    name=name,
                    component_type=_component_type(spec),
                    lifecycle=str(spec.get("lifecycle") or "") or None,
                )
            )
        return components

    async def list_interfaces(self, project: Project) -> list[Interface]:
        del project
        # Backstage APIs lack a component_id for canonical Interfaces; the
        # brain's derived catalog remains the source for interface topology.
        return []

    async def list_resources(self, project: Project) -> list[Resource]:
        resources: list[Resource] = []
        for raw in await self._transport.list_entities("Resource"):
            name = str(raw.get("metadata", {}).get("name") or raw.get("name") or "")
            spec = raw.get("spec", {})
            resources.append(
                Resource(
                    project_id=project.id,
                    name=name,
                    resource_type=_resource_type(spec),
                )
            )
        return resources


def _component_type(spec: dict[str, Any]) -> ComponentType:
    system = str(spec.get("type") or "").lower()
    if system in {"service", "backend", "api"}:
        return ComponentType.BACKEND_SERVICE
    if system in {"website", "frontend", "web"}:
        return ComponentType.FRONTEND_APPLICATION
    if system in {"library", "package"}:
        return ComponentType.LIBRARY
    if system in {"job", "worker", "cron"}:
        return ComponentType.WORKER
    return ComponentType.LIBRARY


def _resource_type(spec: dict[str, Any]) -> ResourceType:
    system = str(spec.get("type") or "").lower()
    if system in {"database", "postgres", "sql"}:
        return ResourceType.POSTGRESQL
    if system == "redis":
        return ResourceType.REDIS
    if system in {"s3", "bucket", "object-storage"}:
        return ResourceType.S3
    if system in {"kafka", "message-broker"}:
        return ResourceType.KAFKA
    return ResourceType.EXTERNAL_SERVICE


__all__ = ["BackstageCatalogAdapter", "BackstageTransport"]
