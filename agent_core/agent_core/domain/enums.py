from __future__ import annotations

from enum import StrEnum


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    PLANNING = "planning"
    AWAITING_REVIEW = "awaiting_review"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"
    FAILED = "failed"


class PlanningSessionStatus(StrEnum):
    INTAKE = "intake"
    NEEDS_CLARIFICATION = "needs_clarification"
    READY_FOR_PLANNING = "ready_for_planning"
    PLAN_DRAFTED = "plan_drafted"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    FAILED = "failed"


class InputMode(StrEnum):
    TEXT = "text"
    DOCUMENT = "document"
    OPENPROJECT = "openproject"
    REPOSITORY = "repository"


class PlanVersionStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class PlanNodeKind(StrEnum):
    VISION = "vision"
    CAPABILITY = "capability"
    EPIC = "epic"
    STORY = "story"
    TASK = "task"


class RequirementStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class ImplementationStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    CONFLICTING = "conflicting"
    UNVERIFIABLE = "unverifiable"


class VerificationOutcome(StrEnum):
    PASSED = "passed"
    CHANGES_REQUIRED = "changes_required"
    BLOCKED = "blocked"
    UNVERIFIABLE = "unverifiable"


class ApprovalScope(StrEnum):
    PLANNING = "planning"
    TASK_COMPLETION = "task_completion"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    CANCELLED = "cancelled"


class RepositoryAccessMode(StrEnum):
    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"


class RetryCategory(StrEnum):
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    RATE_OR_CAPACITY = "RATE_OR_CAPACITY"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    OPTIMISTIC_CONCURRENCY_CONFLICT = "OPTIMISTIC_CONCURRENCY_CONFLICT"
    INVALID_INPUT = "INVALID_INPUT"
    POLICY_DENIED = "POLICY_DENIED"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    PERMANENT_EXTERNAL_ERROR = "PERMANENT_EXTERNAL_ERROR"
    UNKNOWN = "UNKNOWN"


class AgentExecutionStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CodingAttemptStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    ROLLED_BACK = "rolled_back"
