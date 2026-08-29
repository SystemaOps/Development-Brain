"""Domain unit tests for engineering history: Execution, Artifact, Evidence,
VerificationResult, Decision."""

from __future__ import annotations

import uuid

from brain.domain.actors import Actor
from brain.domain.artifacts import Artifact, ArtifactType
from brain.domain.decisions import Decision, DecisionStatus
from brain.domain.evidence import Evidence, EvidenceType
from brain.domain.executions import (
    Execution,
    ExecutionPermissions,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
)
from brain.domain.identity import new_workflow_id
from brain.domain.projects import Project
from brain.domain.verification import VerificationResult, VerificationVerdict
from brain.domain.work_items import WorkItem


def test_execution_links_workflow_work_item_and_executor() -> None:
    project = Project(name="auth")
    executor = Actor(actor_type="agent", display_name="pi")
    work_item = WorkItem(project_id=project.id, title="t")
    execution = Execution(
        workflow_id=new_workflow_id(),
        work_item_id=work_item.id,
        executor_id=executor.id,
    )
    assert execution.status == ExecutionStatus.REQUESTED
    assert execution.completed_at is None
    assert execution.parent_execution_id is None


def test_multiple_executions_have_distinct_ids() -> None:
    project = Project(name="auth")
    executor = Actor(actor_type="agent", display_name="pi")
    work_item = WorkItem(project_id=project.id, title="t")
    first = Execution(
        workflow_id=new_workflow_id(), work_item_id=work_item.id, executor_id=executor.id
    )
    second = Execution(
        workflow_id=new_workflow_id(), work_item_id=work_item.id, executor_id=executor.id
    )
    assert first.id != second.id


def test_execution_permissions_default_to_safe_values() -> None:
    permissions = ExecutionPermissions()
    assert permissions.repository_read is True
    assert permissions.repository_write is False
    assert permissions.shell is False
    assert permissions.network is False
    assert permissions.deploy is False


def test_execution_request_and_result_contract() -> None:
    request = ExecutionRequest(
        execution_id=uuid.uuid4(),
        workflow_id=new_workflow_id(),
        work_item_id=uuid.uuid4(),
        repository_ref="auth-service",
        base_revision="main@91d3a80",
    )
    result = ExecutionResult(
        execution_id=request.execution_id,
        status=ExecutionStatus.COMPLETED,
        modified_files=["services/auth.py"],
        tests_executed=["tests/test_auth.py"],
        observations=["all tests pass"],
    )
    assert result.modified_files == ["services/auth.py"]
    assert result.status == ExecutionStatus.COMPLETED


def test_artifact_and_evidence_chain() -> None:
    project = Project(name="auth")
    artifact = Artifact(project_id=project.id, artifact_type=ArtifactType.DIFF, uri="s3://patch")
    evidence = Evidence(
        execution_id=uuid.uuid4(),
        evidence_type=EvidenceType.GIT_DIFF,
        source="diff --git ...",
        artifact_id=artifact.id,
    )
    assert evidence.artifact_id == artifact.id
    assert artifact.artifact_type == ArtifactType.DIFF


def test_verification_result_verdicts() -> None:
    passed = VerificationResult(execution_id=uuid.uuid4(), verdict=VerificationVerdict.PASS)
    failed = VerificationResult(execution_id=uuid.uuid4(), verdict=VerificationVerdict.FAIL)
    assert passed.verdict == VerificationVerdict.PASS
    assert failed.verdict == VerificationVerdict.FAIL
    assert passed.issues == []


def test_decision_lifecycle() -> None:
    project = Project(name="auth")
    decision = Decision(project_id=project.id, title="Use JWT", decision="Use short-lived JWT")
    assert decision.status == DecisionStatus.PROPOSED
    decision.status = DecisionStatus.ACCEPTED
    assert decision.status == DecisionStatus.ACCEPTED
