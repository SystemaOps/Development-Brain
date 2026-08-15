"""Phase 1 completion gate.

It must be possible to model the canonical chain

    Project -> Requirement -> WorkItem -> Execution -> Artifact + Evidence -> Verification

importing ONLY the brain domain package -- never OpenProject, Jira, Neo4j,
Weaviate, Pi, or LangGraph.
"""

from __future__ import annotations

import uuid

from brain.domain import (
    Actor,
    ActorType,
    Artifact,
    ArtifactType,
    Evidence,
    EvidenceType,
    Execution,
    ExecutionStatus,
    Project,
    Requirement,
    VerificationResult,
    VerificationVerdict,
    WorkItem,
    WorkItemType,
)
from brain.domain.identity import new_workflow_id


def test_completion_gate_models_full_chain() -> None:
    project = Project(name="auth")

    requirement = Requirement(
        project_id=project.id,
        key="REQ-AUTH-12",
        title="Account locking",
        description="Lock accounts after five failed login attempts.",
    )

    work_item = WorkItem(
        project_id=project.id,
        type=WorkItemType.TASK,
        title="Implement account locking",
        requirement_refs=[requirement.id],
    )

    executor = Actor(actor_type=ActorType.AGENT, display_name="pi")
    execution = Execution(
        workflow_id=new_workflow_id(),
        work_item_id=work_item.id,
        executor_id=executor.id,
        status=ExecutionStatus.COMPLETED,
    )

    artifact = Artifact(project_id=project.id, artifact_type=ArtifactType.DIFF)
    evidence = Evidence(
        execution_id=execution.id,
        evidence_type=EvidenceType.GIT_DIFF,
        source="diff --git a/services/auth.py b/services/auth.py",
        artifact_id=artifact.id,
    )

    verification = VerificationResult(
        execution_id=execution.id,
        verdict=VerificationVerdict.PASS,
        issues=[],
        evidence_refs=[evidence.id],
    )

    assert project.id != requirement.id != work_item.id != execution.id
    assert work_item.requirement_refs == [requirement.id]
    assert evidence.execution_id == execution.id
    assert verification.evidence_refs == [evidence.id]


def test_completion_gate_chain_serializes_without_provider_imports() -> None:
    project = Project(name="auth")
    execution = Execution(
        workflow_id=new_workflow_id(),
        work_item_id=uuid.uuid4(),
        executor_id=uuid.uuid4(),
    )
    verification = VerificationResult(execution_id=execution.id, verdict=VerificationVerdict.PASS)
    assert VerificationResult.model_validate_json(verification.model_dump_json()) == verification
    assert Project.model_validate_json(project.model_dump_json()) == project


def test_domain_imports_never_touch_provider_modules() -> None:
    import sys

    provider_modules = {"openproject", "jira", "neo4j", "weaviate", "pi", "langgraph"}
    loaded = {name.split(".")[0] for name in sys.modules}
    assert not (loaded & provider_modules), (
        f"provider modules were loaded while importing the domain: {loaded & provider_modules}"
    )
