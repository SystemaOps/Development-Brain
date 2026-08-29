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
    """Importing the domain in a fresh interpreter must not load providers.

    Runs in a subprocess so adapters already loaded by the rest of the test
    suite (e.g. the Neo4j driver) cannot pollute ``sys.modules`` here.
    """
    import subprocess
    import sys
    from pathlib import Path

    provider_modules = {"openproject", "jira", "neo4j", "weaviate", "pi", "langgraph"}
    providers_repr = repr(sorted(provider_modules))
    code = (
        "import sys\n"
        "import brain.domain  # noqa: F401\n"
        "loaded = {name.split('.')[0] for name in sys.modules}\n"
        f"providers = {{m for m in {providers_repr} if m in loaded}}\n"
        "sys.exit(0 if not providers else 1)\n"
    )
    root = str(Path(__file__).resolve().parent.parent)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=root,
    )
    assert result.returncode == 0, (
        f"provider modules loaded while importing the domain:\n{result.stderr}"
    )
