from __future__ import annotations

from agent_core.ports.approvals import ApprovalRecordStorePort
from agent_core.ports.artifact_store import ArtifactStorePort
from agent_core.ports.coding_attempts import CodingAttemptStorePort
from agent_core.ports.executions import AgentExecutionRecorderPort
from agent_core.ports.project_repository import ProjectRepositoryPort
from agent_core.ports.repository_analysis import RepositoryIndexStorePort


class ExecutionRepository(AgentExecutionRecorderPort):
    """Persists cross-agent execution metadata and status."""


class ArtifactRepository(ArtifactStorePort):
    """Persists typed task artifacts produced by agents."""


class ApprovalRepository(ApprovalRecordStorePort):
    """Persists approval decisions and approval-gate evidence."""


class ProjectRepository(ProjectRepositoryPort):
    """Loads and saves project records for agent workflows."""


class CodingAttemptRepository(CodingAttemptStorePort):
    """Persists coding-attempt execution records."""


class RepositoryIndexRepository(RepositoryIndexStorePort):
    """Persists repository analysis symbols and relationships."""


__all__ = [
    "ApprovalRepository",
    "ArtifactRepository",
    "CodingAttemptRepository",
    "ExecutionRepository",
    "ProjectRepository",
    "RepositoryIndexRepository",
]
