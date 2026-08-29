"""Domain unit tests for WorkItem, including the four status tracks."""

from __future__ import annotations

from brain.domain.common import Priority
from brain.domain.identity import new_requirement_id
from brain.domain.projects import Project
from brain.domain.work_items import (
    AcceptanceCriterion,
    Assignment,
    HumanWorkStatus,
    ImplementationStatus,
    PullRequestStatus,
    VerificationStatus,
    WorkItem,
    WorkItemType,
)


def test_work_item_defaults() -> None:
    project = Project(name="auth")
    item = WorkItem(project_id=project.id, title="Implement account locking")
    assert item.type == WorkItemType.TASK
    assert item.human_work_status == HumanWorkStatus.NEW
    assert item.implementation_status == ImplementationStatus.NOT_STARTED
    assert item.verification_status == VerificationStatus.NOT_VERIFIED
    assert item.pull_request_status == PullRequestStatus.NOT_CREATED


def test_work_item_keeps_four_status_tracks_separate() -> None:
    project = Project(name="auth")
    item = WorkItem(project_id=project.id, title="t")
    # The four tracks can disagree deliberately; this is the point of the model.
    item.human_work_status = HumanWorkStatus.DONE
    item.implementation_status = ImplementationStatus.IMPLEMENTED_UNVERIFIED
    item.verification_status = VerificationStatus.FAILED
    item.pull_request_status = PullRequestStatus.NOT_CREATED
    assert item.human_work_status == HumanWorkStatus.DONE
    assert item.implementation_status == ImplementationStatus.IMPLEMENTED_UNVERIFIED
    assert item.verification_status == VerificationStatus.FAILED
    assert item.pull_request_status == PullRequestStatus.NOT_CREATED


def test_work_item_carries_acceptance_criteria_and_requirement_refs() -> None:
    project = Project(name="auth")
    requirement_id = new_requirement_id()
    item = WorkItem(
        project_id=project.id,
        title="t",
        priority=Priority.HIGH,
        acceptance_criteria=[
            AcceptanceCriterion(description="lock after five failed attempts"),
        ],
        requirement_refs=[requirement_id],
    )
    assert item.acceptance_criteria[0].description == "lock after five failed attempts"
    assert item.requirement_refs == [requirement_id]
    assert item.priority == Priority.HIGH


def test_work_item_assignment() -> None:
    project = Project(name="auth")
    from brain.domain.actors import Actor, ActorType

    executor = Actor(actor_type=ActorType.AGENT, display_name="pi")
    item = WorkItem(
        project_id=project.id,
        title="t",
        assignee=executor.id,
        assignment=Assignment(actor_id=executor.id, role="coder"),
    )
    assert item.assignee == executor.id
    assert item.assignment.role == "coder"


def test_work_item_serializes() -> None:
    project = Project(name="auth")
    item = WorkItem(project_id=project.id, title="t")
    assert WorkItem.model_validate_json(item.model_dump_json()) == item
