"""Deployment-based topology detectors (Task 6.3).

Parses deployment manifests -- Docker Compose, Kubernetes, Helm, Terraform --
to discover services/workers, their container images, resources they depend on,
and the dependencies between them.  Provenance is always ``MANIFEST_ANALYSIS``
with ``DISCOVERED`` origin; confidence reflects how directly the deployment
file states the fact.
"""

from __future__ import annotations

import json

import yaml

from brain.domain.identity import RepositoryId
from brain.domain.knowledge import (
    DiscoveryMethod,
    KnowledgeConfidence,
    KnowledgeEvidence,
    KnowledgeOrigin,
    RevisionScope,
)
from brain.domain.software_model import ComponentType, ResourceType
from brain.domain.topology import (
    ComponentCandidate,
    DependencyCandidate,
    DiscoveredTopology,
    ResourceCandidate,
)

_COMPOSE_SERVICE_TYPES: dict[str, ComponentType] = {
    "worker": ComponentType.WORKER,
    "migrate": ComponentType.WORKER,
    "cron": ComponentType.WORKER,
    "api": ComponentType.BACKEND_SERVICE,
    "app": ComponentType.BACKEND_SERVICE,
    "backend": ComponentType.BACKEND_SERVICE,
    "server": ComponentType.BACKEND_SERVICE,
    "web": ComponentType.FRONTEND_APPLICATION,
    "frontend": ComponentType.FRONTEND_APPLICATION,
}

_RESOURCE_IMAGES: dict[str, tuple[str, str]] = {
    "postgres": ("postgresql", "PostgreSQL"),
    "postgresql": ("postgresql", "PostgreSQL"),
    "mysql": ("postgresql", "PostgreSQL"),
    "redis": ("redis", "Redis"),
    "kafka": ("kafka", "Kafka"),
    "redpanda": ("kafka", "Kafka"),
    "minio": ("minio", "MinIO"),
    "minio/minio": ("minio", "MinIO"),
}

_DEFAULT_COMPOSE_RESOURCES = {
    "database": ("postgresql", "PostgreSQL"),
    "postgres": ("postgresql", "PostgreSQL"),
    "redis": ("redis", "Redis"),
    "cache": ("redis", "Redis"),
    "kafka": ("kafka", "Kafka"),
    "broker": ("message_broker", "MessageBroker"),
    "minio": ("minio", "MinIO"),
    "storage": ("s3", "S3/MinIO"),
    "object-storage": ("s3", "S3/MinIO"),
}


def _evidence(
    revision: str, path: str, confidence: KnowledgeConfidence = KnowledgeConfidence.HIGH
) -> KnowledgeEvidence:
    return KnowledgeEvidence(
        source_type="deployment",
        source_id=path,
        discovery_method=DiscoveryMethod.MANIFEST_ANALYSIS,
        origin=KnowledgeOrigin.DISCOVERED,
        confidence=confidence,
        commit_sha=revision,
        revision_scope=RevisionScope(commit_sha=revision, source_path=path),
    )


class DeploymentTopologyDetector:
    """Discover topology from deployment manifests."""

    def detect(
        self, repository_id: RepositoryId, revision: str, files: dict[str, str]
    ) -> DiscoveredTopology:
        topology = DiscoveredTopology(repository_id=repository_id, revision=revision)

        for path, content in files.items():
            if path in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
                self._compose(topology, repository_id, revision, path, content)
            elif path.endswith(".tf") or path.endswith(".tf.json"):
                self._terraform(topology, repository_id, revision, path, content)
            elif path.endswith((".yaml", ".yml")) and _is_kubernetes_manifest(content):
                self._kubernetes(topology, repository_id, revision, path, content)

        return topology

    def _compose(
        self,
        topology: DiscoveredTopology,
        repository_id: RepositoryId,
        revision: str,
        path: str,
        content: str,
    ) -> None:
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            return
        if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
            return
        for name, spec in data["services"].items():
            if not isinstance(spec, dict):
                continue
            spec_name = str(name)
            component_type = self._compose_type(spec_name, spec)
            topology.components.append(
                ComponentCandidate(
                    name=spec_name,
                    component_type=component_type,
                    repository_id=repository_id,
                    revision=revision,
                    source_paths=[path],
                    provenance=_evidence(revision, path),
                    metadata={"image": str(spec.get("image", "")), "service": spec_name},
                )
            )
            for dependency in _compose_dependencies(spec):
                topology.dependencies.append(
                    DependencyCandidate(
                        source=spec_name,
                        target=_canonical_target(dependency, spec),
                        repository_id=repository_id,
                        revision=revision,
                        source_paths=[path],
                        provenance=_evidence(revision, path, KnowledgeConfidence.MEDIUM),
                    )
                )
        for _name, spec in data["services"].items():
            if not isinstance(spec, dict):
                continue
            image = str(spec.get("image", ""))
            resource_key = image.split("/")[-1].split(":")[0].lower()
            if resource_key in _RESOURCE_IMAGES:
                resource_type, resource_name = _RESOURCE_IMAGES[resource_key]
                if not any(r.name == resource_name for r in topology.resources):
                    topology.resources.append(
                        ResourceCandidate(
                            name=resource_name,
                            resource_type=ResourceType(resource_type),
                            repository_id=repository_id,
                            revision=revision,
                            source_paths=[path],
                            provenance=_evidence(revision, path),
                        )
                    )

    @staticmethod
    def _compose_type(name: str, spec: dict[str, object]) -> ComponentType:
        lowered = name.lower()
        if lowered in _COMPOSE_SERVICE_TYPES:
            return _COMPOSE_SERVICE_TYPES[lowered]
        image = str(spec.get("image", "")).lower()
        for key, component_type in _COMPOSE_SERVICE_TYPES.items():
            if key in image:
                return component_type
        return ComponentType.BACKEND_SERVICE

    def _terraform(
        self,
        topology: DiscoveredTopology,
        repository_id: RepositoryId,
        revision: str,
        path: str,
        content: str,
    ) -> None:
        if path.endswith(".tf.json"):
            self._terraform_json(topology, repository_id, revision, path, content)
            return
        for block in _terraform_blocks(content):
            block_type, label, body = block
            if block_type == "resource":
                resource_type = label
                name = str(body.get("name", ""))
                engine = str(body.get("engine", ""))
                self._record_terraform_resource(
                    topology, repository_id, revision, path, resource_type, name, engine
                )
            elif block_type == "module":
                self._record_module(topology, repository_id, revision, path, body)

    def _terraform_json(
        self,
        topology: DiscoveredTopology,
        repository_id: RepositoryId,
        revision: str,
        path: str,
        content: str,
    ) -> None:
        try:
            data = json.loads(content)
        except ValueError:
            return
        resources = (data.get("resource") or {}) if isinstance(data, dict) else {}
        for resource_type, items in resources.items():
            for name in items:
                self._record_terraform_resource(
                    topology, repository_id, revision, path, resource_type, name
                )

    def _record_terraform_resource(
        self,
        topology: DiscoveredTopology,
        repository_id: RepositoryId,
        revision: str,
        path: str,
        resource_type: str,
        name: str,
        engine: str = "",
    ) -> None:
        lowered = resource_type.lower()
        lowered_engine = engine.lower()
        if (
            any(part in lowered for part in ("postgres", "mysql", "rds"))
            or "postgres" in lowered_engine
            or "mysql" in lowered_engine
        ):
            self._add_resource(topology, repository_id, revision, path, "postgresql", "PostgreSQL")
        elif "redis" in lowered or "elasticache" in lowered or "redis" in lowered_engine:
            self._add_resource(topology, repository_id, revision, path, "redis", "Redis")
        elif "kafka" in lowered or "msk" in lowered or "kafka" in lowered_engine:
            self._add_resource(topology, repository_id, revision, path, "kafka", "Kafka")
        elif "s3" in lowered or "bucket" in lowered:
            self._add_resource(topology, repository_id, revision, path, "s3", "S3/MinIO")

    def _record_module(
        self,
        topology: DiscoveredTopology,
        repository_id: RepositoryId,
        revision: str,
        path: str,
        body: dict[str, object],
    ) -> None:
        source = str(body.get("source", ""))
        lowered = source.lower()
        if "postgres" in lowered or "mysql" in lowered:
            self._add_resource(topology, repository_id, revision, path, "postgresql", "PostgreSQL")
        elif "redis" in lowered:
            self._add_resource(topology, repository_id, revision, path, "redis", "Redis")
        elif "kafka" in lowered:
            self._add_resource(topology, repository_id, revision, path, "kafka", "Kafka")
        elif "s3" in lowered or "bucket" in lowered:
            self._add_resource(topology, repository_id, revision, path, "s3", "S3/MinIO")

    def _add_resource(
        self,
        topology: DiscoveredTopology,
        repository_id: RepositoryId,
        revision: str,
        path: str,
        resource_type: str,
        name: str,
    ) -> None:
        if not any(r.name == name for r in topology.resources):
            topology.resources.append(
                ResourceCandidate(
                    name=name,
                    resource_type=ResourceType(resource_type),
                    repository_id=repository_id,
                    revision=revision,
                    source_paths=[path],
                    provenance=_evidence(revision, path, KnowledgeConfidence.MEDIUM),
                )
            )

    def _kubernetes(
        self,
        topology: DiscoveredTopology,
        repository_id: RepositoryId,
        revision: str,
        path: str,
        content: str,
    ) -> None:
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            return
        kind = str(data.get("kind", "")) if isinstance(data, dict) else ""
        metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
        name = str(metadata.get("name", path.rsplit("/", 1)[-1]))
        if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}:
            topology.components.append(
                ComponentCandidate(
                    name=name,
                    component_type=ComponentType.BACKEND_SERVICE,
                    repository_id=repository_id,
                    revision=revision,
                    source_paths=[path],
                    provenance=_evidence(revision, path, KnowledgeConfidence.MEDIUM),
                )
            )
            for image in _k8s_images(data):
                resource_key = image.split("/")[-1].split(":")[0].lower()
                if resource_key in _RESOURCE_IMAGES:
                    resource_type, resource_name = _RESOURCE_IMAGES[resource_key]
                    if not any(r.name == resource_name for r in topology.resources):
                        topology.resources.append(
                            ResourceCandidate(
                                name=resource_name,
                                resource_type=ResourceType(resource_type),
                                repository_id=repository_id,
                                revision=revision,
                                source_paths=[path],
                                provenance=_evidence(revision, path, KnowledgeConfidence.MEDIUM),
                            )
                        )


def _compose_dependencies(spec: dict[str, object]) -> list[str]:
    deps = spec.get("depends_on")
    if isinstance(deps, list):
        return [str(d) for d in deps]
    if isinstance(deps, dict):
        return [str(k) for k in deps]
    return []


def _canonical_target(service_name: str, spec: dict[str, object]) -> str:
    """Resolve a compose dependency target to its canonical resource name.

    ``postgres`` / ``database`` map to ``PostgreSQL``, ``redis`` / ``cache``
    map to ``Redis``, and so on, so dependency edges line up with the resource
    candidates discovered from images.
    """
    lowered = service_name.lower()
    if lowered in _DEFAULT_COMPOSE_RESOURCES:
        return _DEFAULT_COMPOSE_RESOURCES[lowered][1]
    image = str(spec.get("image", "")).lower()
    resource_key = image.split("/")[-1].split(":")[0]
    if resource_key in _RESOURCE_IMAGES:
        return _RESOURCE_IMAGES[resource_key][1]
    return service_name


def _k8s_images(data: object) -> list[str]:
    images: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "image" and isinstance(value, str):
                    images.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return images


def _is_kubernetes_manifest(content: str) -> bool:
    lowered = content[:4096].lower()
    return "apiversion:" in lowered and "kind:" in lowered


def _terraform_blocks(content: str) -> list[tuple[str, str, dict[str, object]]]:
    """Very small Terraform block parser for the common ``resource``/``module`` forms."""
    blocks: list[tuple[str, str, dict[str, object]]] = []
    pattern = (
        r"(?m)^\s*(resource|module)\s+[\"']?([a-zA-Z0-9_.-]+)[\"']?\s+"
        r"[\"']?([a-zA-Z0-9_.-]+)[\"']?\s*\{"
    )
    import re

    for match in re.finditer(pattern, content):
        block_type, label, name = match.group(1), match.group(2), match.group(3)
        body: dict[str, object] = {"name": name}
        rest = content[match.end() : match.end() + 2000]
        engine = re.search(r"(?m)\bengine\s*=\s*[\"']([^\"']+)[\"']", rest)
        if engine:
            body["engine"] = engine.group(1)
        blocks.append((block_type, label, body))
    return blocks


__all__ = ["DeploymentTopologyDetector"]
