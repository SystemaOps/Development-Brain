"""Resource discovery (Task 6.6).

Detects infrastructure resources -- PostgreSQL, Redis, Kafka, S3/MinIO, message
brokers, external HTTP services -- from manifests and configuration files that
name the resources directly, complementing the deployment detector.
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
from brain.domain.software_model import ResourceType
from brain.domain.topology import DiscoveredTopology, ResourceCandidate

_URL_RESOURCES: list[tuple[re.Pattern[str], tuple[str, str]]] = [
    (re.compile(r"postgres(?:ql)?://", re.IGNORECASE), ("postgresql", "PostgreSQL")),
    (re.compile(r"redis://", re.IGNORECASE), ("redis", "Redis")),
    (re.compile(r"rediss://", re.IGNORECASE), ("redis", "Redis")),
    (re.compile(r"kafka://", re.IGNORECASE), ("kafka", "Kafka")),
    (re.compile(r"s3://", re.IGNORECASE), ("s3", "S3/MinIO")),
]

_ENV_RESOURCES: dict[str, tuple[str, str]] = {
    "DATABASE_URL": ("postgresql", "PostgreSQL"),
    "POSTGRES_URL": ("postgresql", "PostgreSQL"),
    "POSTGRES_HOST": ("postgresql", "PostgreSQL"),
    "REDIS_URL": ("redis", "Redis"),
    "REDIS_HOST": ("redis", "Redis"),
    "KAFKA_BROKERS": ("kafka", "Kafka"),
    "S3_BUCKET": ("s3", "S3/MinIO"),
    "MINIO_URL": ("minio", "MinIO"),
}

_RESOURCE_WORDS: list[tuple[re.Pattern[str], tuple[str, str]]] = [
    (re.compile(r"\bpostgres(?:ql)?\b", re.IGNORECASE), ("postgresql", "PostgreSQL")),
    (re.compile(r"\bredis\b", re.IGNORECASE), ("redis", "Redis")),
    (re.compile(r"\bkafka\b", re.IGNORECASE), ("kafka", "Kafka")),
    (re.compile(r"\bminio\b", re.IGNORECASE), ("minio", "MinIO")),
    (re.compile(r"\bs3\b", re.IGNORECASE), ("s3", "S3/MinIO")),
]

_ANNOTATION_CONFIG = frozenset(
    {"application.properties", "application.yml", "application.yaml", "config.yaml", "config.yml"}
)
_IGNORED = frozenset({"requirements.txt", "pyproject.toml", "package.json", "go.mod"})


def _evidence(revision: str, path: str, confidence: KnowledgeConfidence) -> KnowledgeEvidence:
    return KnowledgeEvidence(
        source_type="config",
        source_id=path,
        discovery_method=DiscoveryMethod.MANIFEST_ANALYSIS,
        origin=KnowledgeOrigin.DISCOVERED,
        confidence=confidence,
        commit_sha=revision,
        revision_scope=RevisionScope(commit_sha=revision, source_path=path),
    )


class ResourceDetector:
    """Discover resource candidates from configuration files."""

    def detect(
        self, repository_id: RepositoryId, revision: str, files: dict[str, str]
    ) -> DiscoveredTopology:
        topology = DiscoveredTopology(repository_id=repository_id, revision=revision)
        for path, content in files.items():
            lower_path = path.lower()
            if lower_path in _IGNORED or lower_path.startswith(
                (".github", ".gitlab", "docs", "tests")
            ):
                continue
            for pattern, (resource_type, name) in _URL_RESOURCES:
                if pattern.search(content):
                    self._add(
                        topology,
                        repository_id,
                        revision,
                        path,
                        resource_type,
                        name,
                        KnowledgeConfidence.HIGH,
                    )
            if lower_path in _ANNOTATION_CONFIG:
                for key, (resource_type, name) in _ENV_RESOURCES.items():
                    if re.search(rf"{re.escape(key)}\s*[:=]", content):
                        self._add(
                            topology,
                            repository_id,
                            revision,
                            path,
                            resource_type,
                            name,
                            KnowledgeConfidence.HIGH,
                        )
            for pattern, (resource_type, name) in _RESOURCE_WORDS:
                if pattern.search(content):
                    self._add(
                        topology,
                        repository_id,
                        revision,
                        path,
                        resource_type,
                        name,
                        KnowledgeConfidence.MEDIUM,
                    )
        return topology

    @staticmethod
    def _add(
        topology: DiscoveredTopology,
        repository_id: RepositoryId,
        revision: str,
        path: str,
        resource_type: str,
        name: str,
        confidence: KnowledgeConfidence,
    ) -> None:
        if not any(r.name == name for r in topology.resources):
            topology.resources.append(
                ResourceCandidate(
                    name=name,
                    resource_type=ResourceType(resource_type),
                    repository_id=repository_id,
                    revision=revision,
                    source_paths=[path],
                    provenance=_evidence(revision, path, confidence),
                )
            )


__all__ = ["ResourceDetector"]
