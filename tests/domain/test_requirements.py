"""Domain unit tests for Requirement and its supporting models."""

from __future__ import annotations

from brain.domain.common import Priority
from brain.domain.projects import Project
from brain.domain.requirements import (
    Constraint,
    ConstraintKind,
    Requirement,
    RequirementSource,
    RequirementSourceType,
    RequirementStatus,
)


def test_requirement_defaults() -> None:
    project = Project(name="auth")
    req = Requirement(project_id=project.id, key="REQ-AUTH-12", title="Account locking")
    assert req.status == RequirementStatus.DRAFT
    assert req.priority is None
    assert req.parent_id is None
    assert req.derived_from == []
    assert req.acceptance_criteria == []
    assert req.constraints == []


def test_requirement_hierarchy() -> None:
    project = Project(name="auth")
    parent = Requirement(project_id=project.id, title="Authentication")
    derived = Requirement(
        project_id=project.id,
        title="Account locking",
        parent_id=parent.id,
        derived_from=[parent.id],
    )
    assert derived.parent_id == parent.id
    assert derived.derived_from == [parent.id]


def test_requirement_constraints_and_criteria() -> None:
    project = Project(name="auth")
    req = Requirement(
        project_id=project.id,
        title="Account locking",
        priority=Priority.CRITICAL,
        constraints=[Constraint(kind=ConstraintKind.MUST, description="lock after 5 failures")],
        source_refs=[
            RequirementSource(
                source_type=RequirementSourceType.DOCUMENT,
                source={
                    "provider": "git_markdown",
                    "reference": "docs/requirements.md#REQ-AUTH-12",
                },
            )
        ],
    )
    assert req.priority == Priority.CRITICAL
    assert req.constraints[0].kind == ConstraintKind.MUST
    assert req.source_refs[0].source_type == RequirementSourceType.DOCUMENT
    assert req.source_refs[0].source.reference == "docs/requirements.md#REQ-AUTH-12"


def test_requirement_serializes() -> None:
    project = Project(name="auth")
    req = Requirement(project_id=project.id, title="t")
    assert Requirement.model_validate_json(req.model_dump_json()) == req
