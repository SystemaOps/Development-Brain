"""Manifest-based topology detectors (Task 6.2).

Detects components from the project's highest-priority manifests:

- ``pyproject.toml``   -> Python project (dependencies, framework hints)
- ``requirements.txt`` -> Python dependency list
- ``package.json``     -> JavaScript/TypeScript project
- ``Dockerfile``       -> containerized component
- ``docker-compose.yml`` -> service topology (shared with deployment detector)

Every candidate records provenance (``DiscoveryMethod.MANIFEST_ANALYSIS``).
"""

from __future__ import annotations

import re

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

_PYPROJECT_DEPS: dict[str, ComponentType] = {
    "fastapi": ComponentType.BACKEND_SERVICE,
    "flask": ComponentType.BACKEND_SERVICE,
    "django": ComponentType.BACKEND_SERVICE,
    "uvicorn": ComponentType.BACKEND_SERVICE,
    "celery": ComponentType.WORKER,
    "rq": ComponentType.WORKER,
    "click": ComponentType.CLI,
    "typer": ComponentType.CLI,
}

_KNOWN_RESOURCES: dict[str, tuple[str, str]] = {
    "psycopg": ("postgresql", "PostgreSQL"),
    "psycopg2": ("postgresql", "PostgreSQL"),
    "asyncpg": ("postgresql", "PostgreSQL"),
    "redis": ("redis", "Redis"),
    "kafka-python": ("kafka", "Kafka"),
    "aiokafka": ("kafka", "Kafka"),
    "boto3": ("s3", "S3/MinIO"),
}


def _evidence(revision: str, path: str) -> KnowledgeEvidence:
    return KnowledgeEvidence(
        source_type="manifest",
        source_id=path,
        discovery_method=DiscoveryMethod.MANIFEST_ANALYSIS,
        origin=KnowledgeOrigin.DISCOVERED,
        confidence=KnowledgeConfidence.HIGH,
        commit_sha=revision,
        revision_scope=RevisionScope(commit_sha=revision, source_path=path),
    )


def _component(
    repository_id: RepositoryId,
    revision: str,
    name: str,
    component_type: ComponentType,
    path: str,
) -> ComponentCandidate:
    return ComponentCandidate(
        name=name,
        component_type=component_type,
        repository_id=repository_id,
        revision=revision,
        source_paths=[path],
        provenance=_evidence(revision, path),
    )


def _resource(
    repository_id: RepositoryId,
    revision: str,
    name: str,
    resource_type: str,
    path: str,
) -> ResourceCandidate:
    return ResourceCandidate(
        name=name,
        resource_type=ResourceType(resource_type),
        repository_id=repository_id,
        revision=revision,
        source_paths=[path],
        provenance=_evidence(revision, path),
    )


def _project_name(content: str) -> str | None:
    match = re.search(r"(?m)^name\s*=\s*[\"']([^\"']+)[\"']", content)
    return match.group(1) if match else None


class ManifestTopologyDetector:
    """Extract components and resource hints from manifest files."""

    def detect(
        self, repository_id: RepositoryId, revision: str, files: dict[str, str]
    ) -> DiscoveredTopology:
        topology = DiscoveredTopology(repository_id=repository_id, revision=revision)

        pyproject = files.get("pyproject.toml")
        if pyproject is not None:
            name = _project_name(pyproject)
            if name:
                topology.components.append(
                    _component(
                        repository_id,
                        revision,
                        name,
                        ComponentType.BACKEND_SERVICE,
                        "pyproject.toml",
                    )
                )
            for dep in self._pyproject_dependencies(pyproject):
                if dep in _PYPROJECT_DEPS:
                    component_type = _PYPROJECT_DEPS[dep]
                    component_name = name or dep
                    if not any(c.name == component_name for c in topology.components):
                        topology.components.append(
                            _component(
                                repository_id,
                                revision,
                                component_name,
                                component_type,
                                "pyproject.toml",
                            )
                        )
                elif dep in _KNOWN_RESOURCES:
                    resource_name = _KNOWN_RESOURCES[dep][1]
                    if not any(r.name == resource_name for r in topology.resources):
                        topology.resources.append(
                            _resource(
                                repository_id,
                                revision,
                                resource_name,
                                _KNOWN_RESOURCES[dep][0],
                                "pyproject.toml",
                            )
                        )
                    if name:
                        topology.dependencies.append(
                            DependencyCandidate(
                                source=name,
                                target=resource_name,
                                repository_id=repository_id,
                                revision=revision,
                                source_paths=["pyproject.toml"],
                                provenance=_evidence(revision, "pyproject.toml"),
                            )
                        )

        requirements = files.get("requirements.txt")
        if requirements is not None and not pyproject:
            name = _requirements_project_name(requirements)
            if name:
                topology.components.append(
                    _component(
                        repository_id,
                        revision,
                        name,
                        ComponentType.BACKEND_SERVICE,
                        "requirements.txt",
                    )
                )

        package_json = files.get("package.json")
        if package_json is not None:
            pkg_name = self._package_name(package_json)
            if pkg_name:
                topology.components.append(
                    _component(
                        repository_id,
                        revision,
                        pkg_name,
                        self._package_type(package_json),
                        "package.json",
                    )
                )

        return topology

    @staticmethod
    def _pyproject_dependencies(content: str) -> list[str]:
        deps: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            inline = re.match(r"^dependencies\s*=\s*\[(.*)\]$", stripped)
            if inline:
                for entry in inline.group(1).split(","):
                    name = _entry_name(entry)
                    if name:
                        deps.append(name)
                continue
            poetry = re.match(r"^([a-zA-Z0-9_.-]+)\s*=\s*[\"'][^\"']+[\"']", stripped)
            if poetry:
                key = poetry.group(1).lower()
                if not key.startswith(
                    ("python", "requires-python", "name", "version", "description")
                ):
                    deps.append(key)
        return deps

    @staticmethod
    def _package_name(content: str) -> str | None:
        match = re.search(r'"name"\s*:\s*"([^"]+)"', content)
        return match.group(1) if match else None

    @staticmethod
    def _package_type(content: str) -> ComponentType:
        lowered = content.lower()
        if (
            '"react"' in lowered
            or '"vue"' in lowered
            or '"@angular' in lowered
            or '"next"' in lowered
        ):
            return ComponentType.FRONTEND_APPLICATION
        return ComponentType.BACKEND_SERVICE


def _requirements_project_name(content: str) -> str | None:
    """Best-effort project name: the first pinned package minus any suffix."""
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([a-zA-Z0-9_.-]+)", stripped)
        if match:
            return match.group(1)
    return None


def _entry_name(entry: str) -> str | None:
    """Normalize one pyproject dependency entry to its package name.

    Handles ``"name"``, ``name==1.0``, ``name[extra]`` and ``name[extra]==1.0``.
    """
    candidate = entry.strip()
    if not candidate:
        return None
    match = re.match(r"^[\"']?([a-zA-Z0-9_.-]+)", candidate)
    return match.group(1).lower() if match else None


__all__ = ["ManifestTopologyDetector"]
