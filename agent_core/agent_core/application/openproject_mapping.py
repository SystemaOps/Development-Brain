from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from agent_core.application.openproject_feedback import OpenProjectFeedbackIntent
from agent_core.domain.enums import (
    PlanNodeKind,
    PlanningSessionStatus,
    PlanVersionStatus,
    ProjectStatus,
    VerificationOutcome,
)


class OpenProjectMappingError(ValueError):
    pass


class OpenProjectSemanticStatus(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    READY_FOR_VERIFICATION = "READY_FOR_VERIFICATION"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    VERIFIED = "VERIFIED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class OpenProjectApprovalState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class OpenProjectResolvedLink:
    name: str
    href: str

    def as_hal_link(self) -> dict[str, str]:
        return {"href": self.href, "title": self.name}


@dataclass(frozen=True)
class OpenProjectResourceCatalog:
    type_hrefs: Mapping[str, str] = field(default_factory=dict)
    status_hrefs: Mapping[str, str] = field(default_factory=dict)
    priority_hrefs: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenProjectSemanticMapping:
    type_names_by_plan_kind: Mapping[PlanNodeKind, str | None] = field(
        default_factory=lambda: {
            PlanNodeKind.VISION: None,
            PlanNodeKind.CAPABILITY: None,
            PlanNodeKind.EPIC: "Epic",
            PlanNodeKind.STORY: "Story",
            PlanNodeKind.TASK: "Task",
        }
    )
    status_names_by_semantic_status: Mapping[OpenProjectSemanticStatus, str] = field(
        default_factory=lambda: {
            OpenProjectSemanticStatus.DRAFT: "Draft",
            OpenProjectSemanticStatus.NEEDS_CLARIFICATION: "Needs clarification",
            OpenProjectSemanticStatus.AWAITING_APPROVAL: "Awaiting approval",
            OpenProjectSemanticStatus.READY: "Ready",
            OpenProjectSemanticStatus.IN_PROGRESS: "In progress",
            OpenProjectSemanticStatus.BLOCKED: "Blocked",
            OpenProjectSemanticStatus.READY_FOR_VERIFICATION: "Ready for verification",
            OpenProjectSemanticStatus.CHANGES_REQUIRED: "Changes required",
            OpenProjectSemanticStatus.VERIFIED: "Verified",
            OpenProjectSemanticStatus.DONE: "Done",
            OpenProjectSemanticStatus.CANCELLED: "Cancelled",
        }
    )
    priority_names_by_normalized_priority: Mapping[str, str] = field(
        default_factory=lambda: {
            "low": "Low",
            "normal": "Normal",
            "medium": "Normal",
            "high": "High",
            "urgent": "Urgent",
            "critical": "Urgent",
            "immediate": "Immediate",
            "blocker": "Immediate",
        }
    )


class OpenProjectSemanticMapper:
    def __init__(
        self,
        *,
        catalog: OpenProjectResourceCatalog,
        mapping: OpenProjectSemanticMapping | None = None,
    ) -> None:
        self.catalog = catalog
        self.mapping = mapping or OpenProjectSemanticMapping()

    def type_link_for_plan_kind(
        self,
        kind: PlanNodeKind | str,
    ) -> OpenProjectResolvedLink | None:
        plan_kind = PlanNodeKind(kind)
        type_name = self.mapping.type_names_by_plan_kind[plan_kind]
        if type_name is None:
            return None
        return self._resolve(
            resource_kind="type",
            name=type_name,
            hrefs=self.catalog.type_hrefs,
        )

    def status_link_for_semantic_status(
        self,
        status: OpenProjectSemanticStatus | str,
    ) -> OpenProjectResolvedLink:
        semantic_status = OpenProjectSemanticStatus(status)
        return self._resolve(
            resource_kind="status",
            name=self.mapping.status_names_by_semantic_status[semantic_status],
            hrefs=self.catalog.status_hrefs,
        )

    def priority_link_for_priority(
        self,
        priority: str | None,
    ) -> OpenProjectResolvedLink | None:
        if not priority:
            return None
        priority_name = self.mapping.priority_names_by_normalized_priority.get(
            _normalize_name(priority)
        )
        if priority_name is None:
            return None
        return self._resolve(
            resource_kind="priority",
            name=priority_name,
            hrefs=self.catalog.priority_hrefs,
        )

    def work_package_links(
        self,
        *,
        kind: PlanNodeKind | str,
        semantic_status: OpenProjectSemanticStatus | str | None = None,
        priority: str | None = None,
    ) -> dict[str, dict[str, str]]:
        links: dict[str, dict[str, str]] = {}
        type_link = self.type_link_for_plan_kind(kind)
        if type_link is not None:
            links["type"] = type_link.as_hal_link()

        if semantic_status is not None:
            links["status"] = self.status_link_for_semantic_status(
                semantic_status
            ).as_hal_link()

        priority_link = self.priority_link_for_priority(priority)
        if priority_link is not None:
            links["priority"] = priority_link.as_hal_link()

        return links

    def semantic_status_for_plan_version(
        self,
        status: PlanVersionStatus | str,
    ) -> OpenProjectSemanticStatus:
        return {
            PlanVersionStatus.DRAFT: OpenProjectSemanticStatus.DRAFT,
            PlanVersionStatus.AWAITING_REVIEW: OpenProjectSemanticStatus.AWAITING_APPROVAL,
            PlanVersionStatus.APPROVED: OpenProjectSemanticStatus.READY,
            PlanVersionStatus.ACTIVE: OpenProjectSemanticStatus.IN_PROGRESS,
            PlanVersionStatus.SUPERSEDED: OpenProjectSemanticStatus.CANCELLED,
            PlanVersionStatus.REJECTED: OpenProjectSemanticStatus.CHANGES_REQUIRED,
        }[PlanVersionStatus(status)]

    def semantic_status_for_planning_session(
        self,
        status: PlanningSessionStatus | str,
    ) -> OpenProjectSemanticStatus:
        return {
            PlanningSessionStatus.INTAKE: OpenProjectSemanticStatus.DRAFT,
            PlanningSessionStatus.NEEDS_CLARIFICATION: OpenProjectSemanticStatus.NEEDS_CLARIFICATION,
            PlanningSessionStatus.READY_FOR_PLANNING: OpenProjectSemanticStatus.READY,
            PlanningSessionStatus.PLAN_DRAFTED: OpenProjectSemanticStatus.AWAITING_APPROVAL,
            PlanningSessionStatus.AWAITING_REVIEW: OpenProjectSemanticStatus.AWAITING_APPROVAL,
            PlanningSessionStatus.APPROVED: OpenProjectSemanticStatus.READY,
            PlanningSessionStatus.FAILED: OpenProjectSemanticStatus.BLOCKED,
        }[PlanningSessionStatus(status)]

    def semantic_status_for_project(
        self,
        status: ProjectStatus | str,
    ) -> OpenProjectSemanticStatus:
        return {
            ProjectStatus.DRAFT: OpenProjectSemanticStatus.DRAFT,
            ProjectStatus.PLANNING: OpenProjectSemanticStatus.IN_PROGRESS,
            ProjectStatus.AWAITING_REVIEW: OpenProjectSemanticStatus.AWAITING_APPROVAL,
            ProjectStatus.ACTIVE: OpenProjectSemanticStatus.READY,
            ProjectStatus.PAUSED: OpenProjectSemanticStatus.BLOCKED,
            ProjectStatus.ARCHIVED: OpenProjectSemanticStatus.DONE,
            ProjectStatus.FAILED: OpenProjectSemanticStatus.BLOCKED,
        }[ProjectStatus(status)]

    def semantic_status_for_verification(
        self,
        outcome: VerificationOutcome | str,
    ) -> OpenProjectSemanticStatus:
        return {
            VerificationOutcome.PASSED: OpenProjectSemanticStatus.VERIFIED,
            VerificationOutcome.CHANGES_REQUIRED: OpenProjectSemanticStatus.CHANGES_REQUIRED,
            VerificationOutcome.BLOCKED: OpenProjectSemanticStatus.BLOCKED,
            VerificationOutcome.UNVERIFIABLE: OpenProjectSemanticStatus.BLOCKED,
        }[VerificationOutcome(outcome)]

    def semantic_status_for_approval(
        self,
        approval: OpenProjectApprovalState | str,
    ) -> OpenProjectSemanticStatus:
        return {
            OpenProjectApprovalState.PENDING: OpenProjectSemanticStatus.AWAITING_APPROVAL,
            OpenProjectApprovalState.APPROVED: OpenProjectSemanticStatus.READY,
            OpenProjectApprovalState.REJECTED: OpenProjectSemanticStatus.CHANGES_REQUIRED,
            OpenProjectApprovalState.CANCELLED: OpenProjectSemanticStatus.CANCELLED,
        }[OpenProjectApprovalState(approval)]

    def semantic_status_for_feedback(
        self,
        intent: OpenProjectFeedbackIntent | str,
    ) -> OpenProjectSemanticStatus | None:
        return {
            OpenProjectFeedbackIntent.NONE: None,
            OpenProjectFeedbackIntent.GENERAL_COMMENT: OpenProjectSemanticStatus.NEEDS_CLARIFICATION,
            OpenProjectFeedbackIntent.REQUIREMENT_CHANGE: OpenProjectSemanticStatus.CHANGES_REQUIRED,
            OpenProjectFeedbackIntent.PLAN_FEEDBACK: OpenProjectSemanticStatus.CHANGES_REQUIRED,
            OpenProjectFeedbackIntent.APPROVAL: OpenProjectSemanticStatus.READY,
            OpenProjectFeedbackIntent.REWORK_REQUEST: OpenProjectSemanticStatus.CHANGES_REQUIRED,
            OpenProjectFeedbackIntent.PAUSE: OpenProjectSemanticStatus.BLOCKED,
            OpenProjectFeedbackIntent.RESUME: OpenProjectSemanticStatus.IN_PROGRESS,
            OpenProjectFeedbackIntent.CANCELLATION: OpenProjectSemanticStatus.CANCELLED,
            OpenProjectFeedbackIntent.AGENT_ECHO: None,
        }[OpenProjectFeedbackIntent(intent)]

    def _resolve(
        self,
        *,
        resource_kind: str,
        name: str,
        hrefs: Mapping[str, str],
    ) -> OpenProjectResolvedLink:
        indexed = {_normalize_name(key): (key, href) for key, href in hrefs.items()}
        normalized_name = _normalize_name(name)
        match = indexed.get(normalized_name)
        if match is None:
            matches = [
                value
                for normalized_key, value in indexed.items()
                if normalized_name in normalized_key or normalized_key in normalized_name
            ]
            if len(matches) == 1:
                match = matches[0]
            elif len(matches) > 1:
                raise OpenProjectMappingError(
                    f"OpenProject {resource_kind} mapping '{name}' is ambiguous"
                )
            else:
                raise OpenProjectMappingError(
                    f"OpenProject {resource_kind} mapping '{name}' was not found"
                )
        resolved_name, href = match
        return OpenProjectResolvedLink(name=resolved_name, href=href)


def _normalize_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())
