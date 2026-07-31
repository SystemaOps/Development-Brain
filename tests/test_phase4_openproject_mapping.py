from __future__ import annotations

import pytest

from agent_core.application.openproject_feedback import OpenProjectFeedbackIntent
from agent_core.application.openproject_mapping import (
    OpenProjectApprovalState,
    OpenProjectMappingError,
    OpenProjectResourceCatalog,
    OpenProjectSemanticMapper,
    OpenProjectSemanticStatus,
)
from agent_core.domain.enums import (
    PlanNodeKind,
    PlanningSessionStatus,
    PlanVersionStatus,
    ProjectStatus,
    VerificationOutcome,
)


def make_mapper() -> OpenProjectSemanticMapper:
    return OpenProjectSemanticMapper(
        catalog=OpenProjectResourceCatalog(
            type_hrefs={
                "Epic": "/api/v3/types/1",
                "Story": "/api/v3/types/2",
                "Task": "/api/v3/types/3",
            },
            status_hrefs={
                "Draft": "/api/v3/statuses/1",
                "Needs clarification": "/api/v3/statuses/2",
                "Awaiting approval": "/api/v3/statuses/3",
                "Ready": "/api/v3/statuses/4",
                "In progress": "/api/v3/statuses/5",
                "Blocked": "/api/v3/statuses/6",
                "Ready for verification": "/api/v3/statuses/7",
                "Changes required": "/api/v3/statuses/8",
                "Verified": "/api/v3/statuses/9",
                "Done": "/api/v3/statuses/10",
                "Cancelled": "/api/v3/statuses/11",
            },
            priority_hrefs={
                "Low": "/api/v3/priorities/1",
                "Normal": "/api/v3/priorities/2",
                "High": "/api/v3/priorities/3",
                "Urgent": "/api/v3/priorities/4",
                "Immediate": "/api/v3/priorities/5",
            },
        )
    )


def test_openproject_mapper_projects_only_epic_story_task_by_default():
    mapper = make_mapper()

    assert mapper.type_link_for_plan_kind(PlanNodeKind.VISION) is None
    assert mapper.type_link_for_plan_kind(PlanNodeKind.CAPABILITY) is None
    assert mapper.type_link_for_plan_kind(PlanNodeKind.EPIC).as_hal_link() == {
        "href": "/api/v3/types/1",
        "title": "Epic",
    }
    assert mapper.type_link_for_plan_kind(PlanNodeKind.STORY).href == "/api/v3/types/2"
    assert mapper.type_link_for_plan_kind(PlanNodeKind.TASK).href == "/api/v3/types/3"


def test_openproject_mapper_builds_hal_links_for_work_package_payloads():
    mapper = make_mapper()

    links = mapper.work_package_links(
        kind=PlanNodeKind.TASK,
        semantic_status=OpenProjectSemanticStatus.IN_PROGRESS,
        priority="critical",
    )

    assert links == {
        "type": {"href": "/api/v3/types/3", "title": "Task"},
        "status": {"href": "/api/v3/statuses/5", "title": "In progress"},
        "priority": {"href": "/api/v3/priorities/4", "title": "Urgent"},
    }


def test_openproject_mapper_converts_internal_statuses_to_semantic_statuses():
    mapper = make_mapper()

    assert mapper.semantic_status_for_plan_version(
        PlanVersionStatus.AWAITING_REVIEW
    ) == OpenProjectSemanticStatus.AWAITING_APPROVAL
    assert mapper.semantic_status_for_planning_session(
        PlanningSessionStatus.NEEDS_CLARIFICATION
    ) == OpenProjectSemanticStatus.NEEDS_CLARIFICATION
    assert mapper.semantic_status_for_project(ProjectStatus.PAUSED) == (
        OpenProjectSemanticStatus.BLOCKED
    )
    assert mapper.semantic_status_for_verification(VerificationOutcome.PASSED) == (
        OpenProjectSemanticStatus.VERIFIED
    )
    assert mapper.semantic_status_for_approval(OpenProjectApprovalState.REJECTED) == (
        OpenProjectSemanticStatus.CHANGES_REQUIRED
    )
    assert mapper.semantic_status_for_feedback(OpenProjectFeedbackIntent.RESUME) == (
        OpenProjectSemanticStatus.IN_PROGRESS
    )
    assert mapper.semantic_status_for_feedback(OpenProjectFeedbackIntent.AGENT_ECHO) is None


def test_openproject_mapper_normalizes_discovered_names_and_priority_aliases():
    mapper = OpenProjectSemanticMapper(
        catalog=OpenProjectResourceCatalog(
            type_hrefs={"epic": "/api/v3/types/1", "story": "/api/v3/types/2", "task": "/api/v3/types/3"},
            status_hrefs={"In-Progress": "/api/v3/statuses/5"},
            priority_hrefs={"Normal Priority": "/api/v3/priorities/2"},
        )
    )

    assert mapper.status_link_for_semantic_status(
        OpenProjectSemanticStatus.IN_PROGRESS
    ).href == "/api/v3/statuses/5"
    assert mapper.priority_link_for_priority("medium").href == "/api/v3/priorities/2"


def test_openproject_mapper_fails_clearly_for_missing_provisioned_mapping():
    mapper = OpenProjectSemanticMapper(
        catalog=OpenProjectResourceCatalog(
            type_hrefs={"Story": "/api/v3/types/2"},
            status_hrefs={},
            priority_hrefs={},
        )
    )

    with pytest.raises(OpenProjectMappingError, match="OpenProject type mapping 'Task'"):
        mapper.type_link_for_plan_kind(PlanNodeKind.TASK)
