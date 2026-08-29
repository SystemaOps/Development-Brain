"""API/interface discovery (Task 6.5).

Detects OpenAPI, AsyncAPI, GraphQL and gRPC/protobuf interface definitions and
turns them into canonical :class:`InterfaceCandidate` entities tied to a
component.  Schema files are matched by name/location; the component link uses
the nearest component discovered from manifests/deployment.
"""

from __future__ import annotations

import json
import re

import yaml

from brain.domain.identity import RepositoryId
from brain.domain.knowledge import (
    DiscoveryMethod,
    KnowledgeConfidence,
    KnowledgeEvidence,
    KnowledgeOrigin,
    RevisionScope,
)
from brain.domain.software_model import InterfaceType
from brain.domain.topology import DiscoveredTopology, InterfaceCandidate

_OPENAPI_NAMES = re.compile(r"(?:openapi|swagger)(?:\.ya?ml|\.json|\.json\.json)?$", re.IGNORECASE)
_OPENAPI_JSON = re.compile(r'"openapi"\s*:\s*"[23]\.')


def _evidence(revision: str, path: str) -> KnowledgeEvidence:
    return KnowledgeEvidence(
        source_type="api_schema",
        source_id=path,
        discovery_method=DiscoveryMethod.MANIFEST_ANALYSIS,
        origin=KnowledgeOrigin.DISCOVERED,
        confidence=KnowledgeConfidence.HIGH,
        commit_sha=revision,
        revision_scope=RevisionScope(commit_sha=revision, source_path=path),
    )


class ApiInterfaceDetector:
    """Discover API/interface candidates from schema and definition files."""

    def detect(
        self,
        repository_id: RepositoryId,
        revision: str,
        files: dict[str, str],
        component_names: list[str],
    ) -> DiscoveredTopology:
        topology = DiscoveredTopology(repository_id=repository_id, revision=revision)
        default_component = component_names[0] if component_names else "unknown"

        for path, content in files.items():
            lower = path.lower()
            interface_type: InterfaceType | None = None
            name: str | None = None
            if (
                lower.startswith("openapi")
                or lower.startswith("swagger")
                or _OPENAPI_NAMES.search(path.rsplit("/", 1)[-1])
            ):
                interface_type = InterfaceType.REST
                name = _openapi_title(content) or path
            elif "asyncapi" in lower:
                interface_type = InterfaceType.MESSAGE_TOPIC
                name = _asyncapi_title(content) or path
            elif lower.endswith(".graphql") or lower.endswith(".graphqls"):
                interface_type = InterfaceType.GRAPHQL
                name = path.rsplit("/", 1)[-1]
            elif lower.endswith(".proto"):
                interface_type = InterfaceType.GRPC
                name = _proto_service(content) or path.rsplit("/", 1)[-1]
            elif lower.endswith(".json") and _OPENAPI_JSON.search(content[:8192]):
                interface_type = InterfaceType.REST
                name = _openapi_title(content) or path

            if interface_type is None or name is None:
                continue
            component_name = self._nearest_component(path, component_names, default_component)
            topology.interfaces.append(
                InterfaceCandidate(
                    name=name,
                    interface_type=interface_type,
                    component_name=component_name,
                    schema_ref=path,
                    repository_id=repository_id,
                    revision=revision,
                    source_paths=[path],
                    provenance=_evidence(revision, path),
                )
            )
        return topology

    @staticmethod
    def _nearest_component(path: str, component_names: list[str], default: str) -> str:
        parts = path.split("/")
        for i in range(len(parts) - 1, -1, -1):
            for name in component_names:
                if name in parts[i]:
                    return name
        return default


def _openapi_title(content: str) -> str | None:
    try:
        if content.lstrip().startswith("{"):
            data = json.loads(content)
            info = data.get("info", {})
            if isinstance(info, dict) and info.get("title"):
                return str(info["title"])
        else:
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                info = data.get("info", {})
                if isinstance(info, dict) and info.get("title"):
                    return str(info["title"])
    except (ValueError, yaml.YAMLError):
        pass
    return None


def _asyncapi_title(content: str) -> str | None:
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            info = data.get("info", {})
            if isinstance(info, dict) and info.get("title"):
                return str(info["title"])
    except yaml.YAMLError:
        pass
    return None


def _proto_service(content: str) -> str | None:
    match = re.search(r"(?m)^\s*service\s+(\w+)", content)
    return match.group(1) if match else None


__all__ = ["ApiInterfaceDetector"]
