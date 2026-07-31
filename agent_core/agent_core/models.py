from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from agent_core.db import Base


def now_utc() -> datetime:
    return datetime.utcnow()


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    source_type: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class RepositoryBindingRecord(Base):
    __tablename__ = "repository_bindings"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "repository_key",
            name="uq_repository_bindings_project_key",
        ),
        CheckConstraint(
            "access_mode IN ('READ_ONLY', 'READ_WRITE')",
            name="ck_repository_bindings_access_mode",
        ),
        Index("idx_repository_bindings_project", "project_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_key: Mapped[str] = mapped_column(String(80), nullable=False)
    mount_path: Mapped[str] = mapped_column(Text, nullable=False)
    access_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="READ_ONLY")
    write_allowlist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    denylist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    command_allowlist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    binding_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class RepositorySymbolRecord(Base):
    __tablename__ = "repository_symbols"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "repository_key",
            "symbol_key",
            name="uq_repository_symbols_project_symbol",
        ),
        Index(
            "idx_repository_symbols_project_repository",
            "project_id",
            "repository_key",
            "kind",
        ),
        Index("idx_repository_symbols_name", "repository_key", "name"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_key: Mapped[str] = mapped_column(String(80), nullable=False)
    symbol_key: Mapped[str] = mapped_column(String(500), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    language: Mapped[str] = mapped_column(String(40), nullable=False)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    parent_symbol_key: Mapped[str | None] = mapped_column(String(500))
    symbol_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class RepositoryRelationshipRecord(Base):
    __tablename__ = "repository_relationships"
    __table_args__ = (
        Index(
            "idx_repository_relationships_project_repository",
            "project_id",
            "repository_key",
            "relationship_type",
        ),
        Index("idx_repository_relationships_source", "repository_key", "source_symbol_key"),
        Index("idx_repository_relationships_target", "repository_key", "target_symbol_key"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_key: Mapped[str] = mapped_column(String(80), nullable=False)
    source_symbol_key: Mapped[str] = mapped_column(String(500), nullable=False)
    target_symbol_key: Mapped[str | None] = mapped_column(String(500))
    target_name: Mapped[str | None] = mapped_column(Text)
    relationship_type: Mapped[str] = mapped_column(String(80), nullable=False)
    relationship_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class CodingAttemptRecord(Base):
    __tablename__ = "coding_attempts"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "repository_key",
            "task_key",
            "attempt_number",
            name="uq_coding_attempts_project_task_attempt",
        ),
        CheckConstraint(
            "status IN ('created', 'running', 'succeeded', 'failed', 'blocked', 'rolled_back')",
            name="ck_coding_attempts_status",
        ),
        Index("idx_coding_attempts_project_task", "project_id", "task_key", "attempt_number"),
        Index("idx_coding_attempts_project_status", "project_id", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_key: Mapped[str] = mapped_column(String(80), nullable=False)
    task_key: Mapped[str] = mapped_column(String(160), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    base_commit_sha: Mapped[str | None] = mapped_column(String(80))
    branch: Mapped[str | None] = mapped_column(String(200))
    changed_files: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    command_results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    rollback_plan: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    final_diff: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class PlanningSession(Base):
    __tablename__ = "planning_sessions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="intake")
    input_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="text")
    original_request: Mapped[str | None] = mapped_column(Text)
    intake_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    planning_session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("planning_sessions.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    title: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ClarificationQuestion(Base):
    __tablename__ = "clarification_questions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    planning_session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("planning_sessions.id", ondelete="CASCADE"), nullable=False)
    question_key: Mapped[str] = mapped_column(String(120), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    answer_format: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PlanVersion(Base):
    __tablename__ = "plan_versions"
    __table_args__ = (UniqueConstraint("project_id", "version_number"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    planning_session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("planning_sessions.id", ondelete="SET NULL"))
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    summary: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    generated_from: Mapped[str] = mapped_column(String(40), nullable=False)
    plan_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlanNodeIdentity(Base):
    __tablename__ = "plan_node_identities"
    __table_args__ = (UniqueConstraint("project_id", "stable_key"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    current_plan_node_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PlanNode(Base):
    __tablename__ = "plan_nodes"
    __table_args__ = (UniqueConstraint("plan_version_id", "node_identity_id"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    plan_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("plan_versions.id", ondelete="CASCADE"), nullable=False)
    node_identity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("plan_node_identities.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    inherited_context: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    local_constraints: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    assumptions: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    expected_outputs: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    likely_components: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    priority: Mapped[str | None] = mapped_column(String(40))
    size_estimate: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="proposed")
    node_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PlanNodeRelation(Base):
    __tablename__ = "plan_node_relations"
    __table_args__ = (UniqueConstraint("plan_version_id", "from_node_id", "to_node_id", "relation_type"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    plan_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("plan_versions.id", ondelete="CASCADE"), nullable=False)
    from_node_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("plan_nodes.id", ondelete="CASCADE"), nullable=False)
    to_node_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("plan_nodes.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(60), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ExternalArtifact(Base):
    __tablename__ = "external_artifacts"
    __table_args__ = (UniqueConstraint("system_name", "artifact_type", "external_id"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    node_identity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("plan_node_identities.id", ondelete="SET NULL"))
    system_name: Mapped[str] = mapped_column(String(60), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_url: Mapped[str | None] = mapped_column(Text)
    external_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class OpenProjectOutboundOperation(Base):
    __tablename__ = "openproject_outbound_operations"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_openproject_outbound_operations_idempotency_key",
        ),
        CheckConstraint(
            "operation_type IN ('create_or_update_work_package', 'add_comment')",
            name="ck_openproject_outbound_operations_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_openproject_outbound_operations_status",
        ),
        Index("idx_openproject_outbound_operations_status", "status", "created_at"),
        Index(
            "idx_openproject_outbound_operations_target",
            "target_artifact_type",
            "target_external_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("external_artifacts.id", ondelete="SET NULL"),
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    target_artifact_type: Mapped[str | None] = mapped_column(String(80))
    target_external_id: Mapped[str | None] = mapped_column(Text)
    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OpenProjectReconciliationSnapshot(Base):
    __tablename__ = "openproject_reconciliation_snapshots"
    __table_args__ = (
        Index(
            "idx_openproject_reconciliation_snapshots_target",
            "target_artifact_type",
            "target_external_id",
            "captured_at",
        ),
        Index(
            "idx_openproject_reconciliation_snapshots_outbound_key",
            "outbound_idempotency_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("external_artifacts.id", ondelete="SET NULL"),
    )
    outbound_idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_external_id: Mapped[str] = mapped_column(Text, nullable=False)
    before_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    before_activities_payload: Mapped[dict | None] = mapped_column(JSONB)
    agent_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    detected_human_edits: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ApprovalRecord(Base):
    __tablename__ = "approval_records"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "source_event_id",
            "approval_scope",
            "decision",
            name="uq_approval_records_source_decision",
        ),
        CheckConstraint(
            "approval_scope IN ('planning', 'task_completion')",
            name="ck_approval_records_scope",
        ),
        CheckConstraint(
            "decision IN ('approved', 'changes_requested', 'cancelled')",
            name="ck_approval_records_decision",
        ),
        Index("idx_approval_records_project_scope", "project_id", "approval_scope", "created_at"),
        Index("idx_approval_records_source_event", "source_system", "source_event_id"),
        Index(
            "idx_approval_records_external_work_package",
            "source_system",
            "external_work_package_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    planning_session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("planning_sessions.id", ondelete="SET NULL"),
    )
    plan_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("plan_versions.id", ondelete="SET NULL"),
    )
    external_artifact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("external_artifacts.id", ondelete="SET NULL"),
    )
    source_system: Mapped[str] = mapped_column(String(60), nullable=False, default="openproject")
    source_event_id: Mapped[str | None] = mapped_column(Text)
    external_project_id: Mapped[str | None] = mapped_column(Text)
    external_work_package_id: Mapped[str | None] = mapped_column(Text)
    external_comment_id: Mapped[str | None] = mapped_column(Text)
    approval_scope: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ProvisioningJob(Base):
    __tablename__ = "provisioning_jobs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result_json: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class ContextCapsule(Base):
    __tablename__ = "context_capsules"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    plan_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("plan_versions.id", ondelete="CASCADE"), nullable=False)
    plan_node_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("plan_nodes.id", ondelete="CASCADE"), nullable=False)
    capsule_type: Mapped[str] = mapped_column(String(60), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    capsule_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    token_estimate: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class WebhookEvent(Base):
    __tablename__ = "pm_webhook_events"
    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('pending', 'processing', 'processed', 'failed', 'dead_letter')",
            name="ck_pm_webhook_events_processing_status",
        ),
        Index("idx_pm_webhook_events_status", "processing_status", "received_at"),
        Index("idx_pm_webhook_events_work_package", "external_work_package_id"),
        Index("idx_pm_webhook_events_retry", "processing_status", "retry_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    source_tool: Mapped[str] = mapped_column(Text, nullable=False, default="openproject")
    event_type: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    external_project_id: Mapped[str | None] = mapped_column(Text)
    external_work_package_id: Mapped[str | None] = mapped_column(Text)
    external_comment_id: Mapped[str | None] = mapped_column(Text)
    headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    processing_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class AgentJob(Base):
    __tablename__ = "agent_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'dead_letter')",
            name="ck_agent_jobs_status",
        ),
        Index("idx_agent_jobs_status", "status", "created_at"),
        Index("idx_agent_jobs_retry", "status", "retry_at"),
        Index("idx_agent_jobs_lease", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pm_webhook_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(Text, nullable=False, default="process_pm_event")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[dict | None] = mapped_column(JSONB)


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'running', 'waiting', 'succeeded', 'failed', 'cancelled')",
            name="ck_agent_executions_status",
        ),
        Index("idx_agent_executions_thread_started", "thread_id", "started_at"),
        Index("idx_agent_executions_project_status", "project_id", "status"),
        Index("idx_agent_executions_trigger_event", "trigger_event_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_event_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pm_webhook_events.id", ondelete="SET NULL"),
    )
    parent_execution_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_executions.id", ondelete="SET NULL"),
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="created")
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class AgentPlatformCheckpointRecord(Base):
    __tablename__ = "agent_platform_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "project_key",
            "workflow_id",
            "agent_type",
            "agent_instance_id",
            "execution_id",
            "thread_id",
            "checkpoint_id",
            name="uq_agent_platform_checkpoints_identity",
        ),
        Index(
            "idx_agent_platform_checkpoints_namespace",
            "project_key",
            "workflow_id",
            "agent_type",
            "agent_instance_id",
            "created_at",
        ),
        Index(
            "idx_agent_platform_checkpoints_execution",
            "execution_id",
            "agent_type",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_key: Mapped[str] = mapped_column(String(80), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(80), nullable=False)
    agent_instance_id: Mapped[str] = mapped_column(String(160), nullable=False)
    execution_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    checkpoint_id: Mapped[str] = mapped_column(String(120), nullable=False)
    checkpoint_key: Mapped[str] = mapped_column(Text, nullable=False)
    state_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class AgentPlatformResultRecord(Base):
    __tablename__ = "agent_platform_results"
    __table_args__ = (
        Index("idx_agent_platform_results_execution", "execution_id", "agent_type", "created_at"),
        Index("idx_agent_platform_results_project_status", "project_key", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_key: Mapped[str] = mapped_column(String(80), nullable=False)
    task_key: Mapped[str | None] = mapped_column(String(160))
    agent_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    next_action: Mapped[str | None] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    result_type: Mapped[str] = mapped_column(String(120), nullable=False)
    result_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AgentPlatformFlowRecord(Base):
    __tablename__ = "agent_platform_flows"
    __table_args__ = (
        UniqueConstraint(
            "project_key",
            "workflow_id",
            name="uq_agent_platform_flows_project_workflow",
        ),
        CheckConstraint(
            "status IN ("
            "'queued', 'running', 'completed', 'waiting_for_approval', "
            "'waiting_for_clarification', 'transition_pending', 'escalated', "
            "'max_steps_exceeded', 'changes_requested', 'cancelled'"
            ")",
            name="ck_agent_platform_flows_status",
        ),
        Index(
            "idx_agent_platform_flows_project_status",
            "project_key",
            "status",
            "updated_at",
        ),
        Index(
            "idx_agent_platform_flows_current_execution",
            "current_execution_id",
            "updated_at",
        ),
        Index(
            "idx_agent_platform_flows_recoverable",
            "status",
            "lease_expires_at",
        ),
        Index(
            "idx_agent_platform_flows_claimable",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    workflow_id: Mapped[str] = mapped_column(String(120), nullable=False)
    project_key: Mapped[str] = mapped_column(String(80), nullable=False)
    task_key: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_agent_type: Mapped[str | None] = mapped_column(String(80))
    current_execution_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    pending_action: Mapped[str | None] = mapped_column(String(80))
    pending_agent_type: Mapped[str | None] = mapped_column(String(80))
    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    resume_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_approval_decision: Mapped[str | None] = mapped_column(String(40))
    flow_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_utc,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_utc,
        onupdate=now_utc,
    )


class OpenProjectContextSnapshot(Base):
    __tablename__ = "pm_context_snapshots"
    __table_args__ = (
        Index("idx_pm_context_snapshots_wp", "external_work_package_id", "synced_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_tool: Mapped[str] = mapped_column(Text, nullable=False, default="openproject")
    external_work_package_id: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    status_name: Mapped[str | None] = mapped_column(Text)
    type_name: Mapped[str | None] = mapped_column(Text)
    project_name: Mapped[str | None] = mapped_column(Text)
    description_raw: Mapped[str | None] = mapped_column(Text)
    work_package_payload: Mapped[dict | None] = mapped_column(JSONB)
    activities_payload: Mapped[dict | None] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
