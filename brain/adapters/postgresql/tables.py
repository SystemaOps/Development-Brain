"""SQLAlchemy ORM models for the canonical transactional state.

These rows are the durable, restart-safe representation of the domain model.
References between aggregates are stored as plain ``UUID`` columns with
indexes (soft references): referential integrity is owned by the application
layer / Unit of Work, never by an external provider, and contract tests may
construct aggregates without materializing every dependency first.

Complex value objects (``ExternalReference``, ``AcceptanceCriterion``,
provenance lists, ``dict`` payloads, ...) are stored as JSONB columns.
Revision/provenance columns (``commit_sha``, ``checksum``, ``ingested_at``)
live on the tables that carry versioned knowledge.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by every PostgreSQL row model."""


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True)


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50))
    repositories: Mapped[list[str]] = mapped_column(JSONB, default=list)
    external_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)


class RepositoryRow(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(255))
    clone_url: Mapped[str] = mapped_column(Text)
    default_branch: Mapped[str] = mapped_column(String(255))
    current_revision: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_repositories_project_id", "project_id"),)


class ActorRow(Base):
    __tablename__ = "actors"

    id: Mapped[uuid.UUID] = _uuid_pk()
    actor_type: Mapped[str] = mapped_column(String(50))
    display_name: Mapped[str] = mapped_column(String(255))
    capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list)


class WorkItemRow(Base):
    __tablename__ = "work_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assignee: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assignment: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    acceptance_criteria: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    requirement_refs: Mapped[list[str]] = mapped_column(JSONB, default=list)
    external_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    human_work_status: Mapped[str] = mapped_column(String(50))
    implementation_status: Mapped[str] = mapped_column(String(50))
    verification_status: Mapped[str] = mapped_column(String(50))
    pull_request_status: Mapped[str] = mapped_column(String(50))

    __table_args__ = (
        Index("ix_work_items_project_id", "project_id"),
        Index("ix_work_items_parent_id", "parent_id"),
    )


class RequirementRow(Base):
    __tablename__ = "requirements"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50))
    priority: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    derived_from: Mapped[list[str]] = mapped_column(JSONB, default=list)
    acceptance_criteria: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    constraints: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    source_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)

    __table_args__ = (
        Index("ix_requirements_project_id", "project_id"),
        Index("ix_requirements_parent_id", "parent_id"),
    )


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    source: Mapped[dict[str, object]] = mapped_column(JSONB)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    external_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_documents_project_id", "project_id"),)


class DocumentVersionRow(Base):
    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checksum: Mapped[str] = mapped_column(String(255))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_document_versions_document_id", "document_id"),)


class DocumentNodeRow(Base):
    __tablename__ = "document_nodes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    node_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    heading_path: Mapped[list[str]] = mapped_column(JSONB, default=list)
    content: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    child_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    code_refs: Mapped[list[str]] = mapped_column(JSONB, default=list)
    requirement_refs: Mapped[list[str]] = mapped_column(JSONB, default=list)
    work_item_refs: Mapped[list[str]] = mapped_column(JSONB, default=list)
    links: Mapped[list[str]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_document_nodes_version_id", "version_id"),)


class DecisionRow(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(500))
    context: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str] = mapped_column(Text, default="")
    alternatives: Mapped[list[str]] = mapped_column(JSONB, default=list)
    consequences: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(50))
    source_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    external_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_decisions_project_id", "project_id"),)


class ExecutionRow(Base):
    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    work_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    executor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    context_capsule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parent_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (Index("ix_executions_work_item_id", "work_item_id"),)


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    artifact_type: Mapped[str] = mapped_column(String(50))
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (Index("ix_artifacts_project_id", "project_id"),)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = _uuid_pk()
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    evidence_type: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(Text)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    __table_args__ = (Index("ix_evidence_execution_id", "execution_id"),)


class VerificationResultRow(Base):
    __tablename__ = "verification_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    verdict: Mapped[str] = mapped_column(String(50))
    requirement_results: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    test_results: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    architecture_results: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    static_analysis_results: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    issues: Mapped[list[str]] = mapped_column(JSONB, default=list)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_verification_results_execution_id", "execution_id"),)


class ExternalReferenceRow(Base):
    __tablename__ = "external_references"

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_type: Mapped[str] = mapped_column(String(50))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(500))
    external_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    namespace: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "owner_type",
            "owner_id",
            "provider",
            "external_id",
            name="uq_external_references_owner_provider_external",
        ),
        Index("ix_external_references_owner", "owner_type", "owner_id"),
        Index("ix_external_references_provider_external", "provider", "external_id"),
    )


metadata = Base.metadata
