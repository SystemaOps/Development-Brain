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

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    unresolved_refs: Mapped[list[str]] = mapped_column(JSONB, default=list)

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


class IdempotencyKeyRow(Base):
    """Deduplication record for external (provider) events.

    The key is the provider webhook ID / commit SHA + event / document
    version ID; it is the primary key so redelivered events are skipped.
    """

    __tablename__ = "idempotency_keys"

    idempotency_key: Mapped[str] = mapped_column(String(500), primary_key=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EventLogRow(Base):
    """Append-only log of processed canonical events.

    Rows keep the full correlation/causation chain so an operational flow
    (webhook -> ingestion -> context -> execution -> verification) can be
    traced through one ``correlation_id``.
    """

    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    event_type: Mapped[str] = mapped_column(String(100))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    causation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(String(255))
    idempotency_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    __table_args__ = (Index("ix_event_log_correlation_id", "correlation_id"),)


class RepositorySnapshotRow(Base):
    """Repository tree summarized at one exact revision (Phase 4)."""

    __tablename__ = "repository_snapshots"

    id: Mapped[uuid.UUID] = _uuid_pk()
    repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    revision: Mapped[str] = mapped_column(String(255))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tree: Mapped[list[str]] = mapped_column(JSONB, default=list)
    languages: Mapped[list[str]] = mapped_column(JSONB, default=list)
    manifest_files: Mapped[list[str]] = mapped_column(JSONB, default=list)
    dockerfiles: Mapped[list[str]] = mapped_column(JSONB, default=list)
    compose_files: Mapped[list[str]] = mapped_column(JSONB, default=list)
    ci_configuration: Mapped[list[str]] = mapped_column(JSONB, default=list)
    documentation_roots: Mapped[list[str]] = mapped_column(JSONB, default=list)
    test_roots: Mapped[list[str]] = mapped_column(JSONB, default=list)

    __table_args__ = (
        UniqueConstraint("repository_id", "revision", name="uq_repository_snapshots_repo_revision"),
        Index("ix_repository_snapshots_repository_id", "repository_id"),
    )


class RepositoryChangeSetRow(Base):
    """Classified set of files changed between two revisions (Phase 4)."""

    __tablename__ = "repository_change_sets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    old_revision: Mapped[str | None] = mapped_column(String(255), nullable=True)
    new_revision: Mapped[str] = mapped_column(String(255))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    files: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_repository_change_sets_repository_id", "repository_id"),)


class SoftwareDomainRow(Base):
    """Canonical software domain (Phase 6)."""

    __tablename__ = "software_domains"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    external_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_software_domains_project_id", "project_id"),)


class SystemRow(Base):
    __tablename__ = "systems"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    domain_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    component_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    external_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_systems_project_id", "project_id"),)


class SoftwareComponentRow(Base):
    __tablename__ = "software_components"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(500))
    component_type: Mapped[str] = mapped_column(String(50))
    repository_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    owner: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lifecycle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provenance: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    external_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_software_components_project_id", "project_id"),)


class InterfaceRow(Base):
    __tablename__ = "interfaces"

    id: Mapped[uuid.UUID] = _uuid_pk()
    component_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(500))
    schema_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_interfaces_component_id", "component_id"),)


class ResourceRow(Base):
    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(500))
    resource_type: Mapped[str] = mapped_column(String(50))
    external_refs: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    provenance: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_resources_project_id", "project_id"),)


class TopologyClaimRow(Base):
    """A single reconciliation claim about a topology entity (Phase 6).

    Claims are never overwritten: declared / discovered / inferred facts about
    the same entity all persist so disagreement is preserved.
    """

    __tablename__ = "topology_claims"

    id: Mapped[uuid.UUID] = _uuid_pk()
    entity_kind: Mapped[str] = mapped_column(String(30))
    entity_name: Mapped[str] = mapped_column(String(500))
    attribute: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(String(100))
    repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    revision: Mapped[str] = mapped_column(String(255))
    origin: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[str] = mapped_column(String(30))
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_topology_claims_repository_id", "repository_id"),
        Index("ix_topology_claims_entity", "entity_kind", "entity_name"),
    )


class TopologyDependencyRow(Base):
    """A persisted dependency between two topology entities (Phase 6)."""

    __tablename__ = "topology_dependencies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(500))
    target: Mapped[str] = mapped_column(String(500))
    relation: Mapped[str] = mapped_column(String(50))
    repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    revision: Mapped[str] = mapped_column(String(255))
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    __table_args__ = (Index("ix_topology_dependencies_project", "project_id", "source"),)


class CodeSymbolRow(Base):
    """A parsed code symbol at one repository revision (Phase 7)."""

    __tablename__ = "code_symbols"

    id: Mapped[uuid.UUID] = _uuid_pk()
    repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    revision: Mapped[str] = mapped_column(String(255))
    module: Mapped[str] = mapped_column(String(500))
    qualified_name: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(500))
    path: Mapped[str] = mapped_column(String(1000))
    identity_key: Mapped[str] = mapped_column(String(1500))
    location: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    parameters: Mapped[list[str]] = mapped_column(JSONB, default=list)
    return_annotation: Mapped[str | None] = mapped_column(Text, nullable=True)
    decorators: Mapped[list[str]] = mapped_column(JSONB, default=list)
    docstring: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_code_symbols_repo_revision", "repository_id", "revision"),
        Index("ix_code_symbols_identity_key", "identity_key"),
        Index("ix_code_symbols_qualified", "repository_id", "qualified_name"),
    )


class CodeRelationRow(Base):
    """A typed relation between two code symbols at one revision (Phase 7)."""

    __tablename__ = "code_relations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    revision: Mapped[str] = mapped_column(String(255))
    relation_type: Mapped[str] = mapped_column(String(50))
    source_identity_key: Mapped[str] = mapped_column(String(1500))
    target_identity_key: Mapped[str] = mapped_column(String(1500))
    source_path: Mapped[str] = mapped_column(String(1000))
    target_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    relation_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_code_relations_repo_revision", "repository_id", "revision"),
        Index("ix_code_relations_source", "source_identity_key"),
        Index("ix_code_relations_target", "target_identity_key"),
    )


class CodeFileRow(Base):
    """A parsed source file at one repository revision (Phase 7)."""

    __tablename__ = "code_files"

    id: Mapped[uuid.UUID] = _uuid_pk()
    repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    revision: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(1000))
    module: Mapped[str] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(50))
    content_hash: Mapped[str] = mapped_column(String(64))
    file_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        UniqueConstraint("repository_id", "revision", "path", name="uq_code_files_repo_rev_path"),
    )


class ContextCapsuleRow(Base):
    """A built context capsule for later evaluation (Phase 10)."""

    __tablename__ = "context_capsules"

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[str] = mapped_column(String(20))
    work_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    context_type: Mapped[str] = mapped_column(String(30))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revision: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    candidates: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    allocations: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    model_budget_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capsule_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_context_capsules_work_item", "work_item_id"),
        Index("ix_context_capsules_created", "created_at"),
    )


class PlanRow(Base):
    """A reconciled engineering plan (Phase 11)."""

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    items: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    assessments: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    evidence: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    validation_errors: Mapped[list[str]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_plans_project_id", "project_id"),)


class VerificationRunRow(Base):
    """A persisted verification run (Phase 13)."""

    __tablename__ = "verification_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    plan: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    verdict: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issues: Mapped[list[str]] = mapped_column(JSONB, default=list)
    feedback: Mapped[list[str]] = mapped_column(JSONB, default=list)
    pr_allowed: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_verification_runs_execution", "execution_id"),)


class WorkManagementMappingRow(Base):
    """Internal<->external work item mapping (Phase 14)."""

    __tablename__ = "work_management_mappings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    work_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(50))
    external_id: Mapped[str] = mapped_column(String(500))
    sync_state: Mapped[str] = mapped_column(String(30))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("work_item_id", "provider", name="uq_work_management_mapping"),
    )


class SyncConflictRow(Base):
    """A provider/brain disagreement that must not be overwritten (Phase 14)."""

    __tablename__ = "sync_conflicts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    work_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(50))
    external_id: Mapped[str] = mapped_column(String(500))
    provider_field: Mapped[str] = mapped_column(String(100))
    provider_value: Mapped[str] = mapped_column(String(500))
    brain_value: Mapped[str] = mapped_column(String(500))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_sync_conflicts_work_item", "work_item_id"),)


class WorkflowCheckpointRow(Base):
    """A persisted workflow checkpoint (Phase 16).

    Conceptually separate from domain execution records: it answers "where
    should orchestration resume", not "what engineering work happened".
    """

    __tablename__ = "workflow_checkpoints"

    id: Mapped[uuid.UUID] = _uuid_pk()
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    state: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_workflow_checkpoints_workflow", "workflow_id"),)


class ApprovalRow(Base):
    """A persisted human-approval request (Phase 17)."""

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    approval_type: Mapped[str] = mapped_column(String(30))
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text, default="")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_approvals_work_item", "work_item_id"),
        Index("ix_approvals_workflow", "workflow_id"),
    )


class ExecutionMetricsRow(Base):
    """Per-execution operational metrics (Phase 18)."""

    __tablename__ = "execution_metrics"

    id: Mapped[uuid.UUID] = _uuid_pk()
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    tool_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    commands_executed: Mapped[list[str]] = mapped_column(JSONB, default=list)
    retries: Mapped[int] = mapped_column(BigInteger, default=0)
    verification_outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (Index("ix_execution_metrics_workflow", "workflow_id"),)


class ContextMetricsRow(Base):
    """Per-capsule context metrics (Phase 18)."""

    __tablename__ = "context_metrics"

    id: Mapped[uuid.UUID] = _uuid_pk()
    context_capsule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    work_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    context_token_count: Mapped[int] = mapped_column(BigInteger, default=0)
    candidate_count: Mapped[int] = mapped_column(BigInteger, default=0)
    selected_entity_count: Mapped[int] = mapped_column(BigInteger, default=0)
    retrieval_source_distribution: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    jit_retrieval_requests: Mapped[int] = mapped_column(BigInteger, default=0)
    selected_context: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)

    __table_args__ = (Index("ix_context_metrics_execution", "execution_id"),)


class ContextOutcomeRow(Base):
    """Context-quality outcome signals (Phase 18)."""

    __tablename__ = "context_outcomes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    missing_files_discovered_later: Mapped[list[str]] = mapped_column(JSONB, default=list)
    verifier_omitted_dependencies: Mapped[list[str]] = mapped_column(JSONB, default=list)
    additional_context_requests: Mapped[int] = mapped_column(BigInteger, default=0)
    irrelevant_context_rate: Mapped[float] = mapped_column(Float, default=0.0)
    retry_caused_by_context_failure: Mapped[bool] = mapped_column(Boolean, default=False)


class ImpactMetricsRow(Base):
    """Predicted vs actual impact metrics (Phase 18)."""

    __tablename__ = "impact_metrics"

    id: Mapped[uuid.UUID] = _uuid_pk()
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    predicted_files: Mapped[list[str]] = mapped_column(JSONB, default=list)
    actual_changed_files: Mapped[list[str]] = mapped_column(JSONB, default=list)


class RuntimeObservationRow(Base):
    """One observed runtime fact (Phase 19)."""

    __tablename__ = "runtime_observations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(String(30))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revision: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(Text, default="")
    target: Mapped[str] = mapped_column(Text, default="")
    symbols: Mapped[list[str]] = mapped_column(JSONB, default=list)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_runtime_observations_revision", "repository_id", "revision"),
        Index("ix_runtime_observations_execution", "execution_id"),
    )


class ExecutorQualityRow(Base):
    """Per-task-type executor quality (Phase 20)."""

    __tablename__ = "executor_quality"

    id: Mapped[uuid.UUID] = _uuid_pk()
    executor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    task_type: Mapped[str] = mapped_column(String(100))
    successes: Mapped[int] = mapped_column(BigInteger, default=0)
    failures: Mapped[int] = mapped_column(BigInteger, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_retries: Mapped[int] = mapped_column(BigInteger, default=0)
    total_duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("executor_id", "task_type", name="uq_executor_quality"),
        Index("ix_executor_quality_task_type", "task_type"),
    )


class ContextFeedbackRow(Base):
    """Context ranking feedback (Phase 20)."""

    __tablename__ = "context_feedback"

    id: Mapped[uuid.UUID] = _uuid_pk()
    work_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(50))
    signal: Mapped[str] = mapped_column(Text, default="")
    previous_weights: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    adjusted_weights: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_context_feedback_work_item", "work_item_id"),)


class CommandFailureRow(Base):
    """Persisted command-processing failures (Phase 25)."""

    __tablename__ = "command_failures"

    id: Mapped[uuid.UUID] = _uuid_pk()
    command_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    command_type: Mapped[str] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(BigInteger, default=1)
    category: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text, default="")
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    retry_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_command_failures_command", "command_id"),)


metadata = Base.metadata
