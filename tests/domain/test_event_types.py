"""Round-trip tests for typed canonical event payloads (Task 3.2)."""

from __future__ import annotations

import uuid

from brain.domain import (
    Document,
    DocumentChanged,
    DocumentSource,
    Execution,
    ExecutionCompleted,
    ExecutionRequested,
    ExecutionResult,
    ExecutionStarted,
    ExecutionStatus,
    ExternalReference,
    HumanFeedbackReceived,
    KnowledgeConflictDetected,
    ObservationAcknowledged,
    ObservationCreated,
    ObservationResolved,
    Project,
    ProjectCreated,
    PullRequestCreated,
    PullRequestRequested,
    Repository,
    RepositoryRegistered,
    RepositoryRevisionChanged,
    Requirement,
    RequirementChanged,
    VerificationCompleted,
    VerificationRequested,
    VerificationResult,
    VerificationVerdict,
    WorkItem,
    WorkItemAssigned,
    WorkItemChanged,
    WorkItemCreated,
    derive_event,
    event_to_model,
    model_to_envelope,
)
from brain.domain.event_types import EVENT_TYPE_TO_MODEL, CanonicalEvent, FeedbackVerdict
from brain.domain.events import EventEnvelope, EventType
from brain.domain.identity import (
    RepositoryId,
    WorkflowId,
    new_actor_id,
    new_execution_id,
    new_project_id,
    new_work_item_id,
)


def _sample(model: type[CanonicalEvent]) -> CanonicalEvent:
    project_id = new_project_id()
    if model is ProjectCreated:
        return ProjectCreated(project=Project(name="p"))
    if model is RepositoryRegistered:
        return RepositoryRegistered(
            repository=Repository(project_id=project_id, name="r", clone_url="git@x:r.git")
        )
    if model is RepositoryRevisionChanged:
        return RepositoryRevisionChanged(
            repository_id=RepositoryId(uuid.uuid4()),
            old_revision="old",
            new_revision="new",
        )
    if model is DocumentChanged:
        return DocumentChanged(
            document=Document(
                project_id=project_id,
                title="d",
                source=DocumentSource(provider="git", uri="README.md"),
            )
        )
    if model is WorkItemCreated:
        return WorkItemCreated(work_item=WorkItem(project_id=project_id, title="t"))
    if model is WorkItemChanged:
        return WorkItemChanged(work_item=WorkItem(project_id=project_id, title="t"))
    if model is WorkItemAssigned:
        return WorkItemAssigned(
            work_item_id=new_work_item_id(),
            actor_id=new_actor_id(),
            assigned_by=new_actor_id(),
        )
    if model is RequirementChanged:
        return RequirementChanged(requirement=Requirement(project_id=project_id, title="r"))
    if model is ExecutionRequested:
        return ExecutionRequested(execution=_execution())
    if model is ExecutionStarted:
        return ExecutionStarted(execution=_execution())
    if model is ExecutionCompleted:
        return ExecutionCompleted(execution=_execution(), result=_result())
    if model is VerificationRequested:
        return VerificationRequested(
            execution_id=new_execution_id(),
            work_item_id=new_work_item_id(),
        )
    if model is VerificationCompleted:
        return VerificationCompleted(
            verification=VerificationResult(
                execution_id=new_execution_id(), verdict=VerificationVerdict.PASS
            )
        )
    if model is PullRequestRequested:
        return PullRequestRequested(
            project_id=project_id,
            work_item_id=new_work_item_id(),
            repository_id=RepositoryId(uuid.uuid4()),
            base_revision="main",
            head_revision="feature",
        )
    if model is PullRequestCreated:
        return PullRequestCreated(
            project_id=project_id,
            work_item_id=new_work_item_id(),
            external_ref=ExternalReference(provider="github", external_id="42"),
        )
    if model is HumanFeedbackReceived:
        return HumanFeedbackReceived(
            work_item_id=new_work_item_id(),
            actor_id=new_actor_id(),
            verdict=FeedbackVerdict.APPROVED,
        )
    if model is KnowledgeConflictDetected:
        return KnowledgeConflictDetected(
            entity_id=uuid.uuid4(),
            entity_type="requirement",
            claim_a="a",
            claim_b="b",
            source_a="src-a",
            source_b="src-b",
        )
    if model is ObservationCreated:
        return ObservationCreated(
            observation_id=uuid.uuid4(),
            project_id=project_id,
            observation_type="discovery",
            title="Found something",
        )
    if model is ObservationAcknowledged:
        return ObservationAcknowledged(
            observation_id=uuid.uuid4(),
            project_id=project_id,
        )
    if model is ObservationResolved:
        return ObservationResolved(
            observation_id=uuid.uuid4(),
            project_id=project_id,
        )
    raise AssertionError(f"no sample for {model.__name__}")


def _execution() -> Execution:
    return Execution(
        workflow_id=WorkflowId(uuid.uuid4()),
        work_item_id=new_work_item_id(),
        executor_id=new_actor_id(),
    )


def _result() -> ExecutionResult:
    return ExecutionResult(execution_id=new_execution_id(), status=ExecutionStatus.COMPLETED)


def test_every_canonical_type_has_a_model() -> None:
    assert set(EVENT_TYPE_TO_MODEL) == set(EventType)


def test_every_model_round_trips_through_envelope() -> None:
    for model_type, model_cls in EVENT_TYPE_TO_MODEL.items():
        sample = _sample(model_cls)
        envelope = model_to_envelope(sample, source="test", idempotency_key="k")
        assert envelope.event_type == model_type
        assert envelope.idempotency_key == "k"
        parsed = event_to_model(envelope)
        assert parsed is not None
        assert type(parsed) is model_cls
        assert parsed == sample


def test_malformed_payload_parses_to_none() -> None:
    envelope = EventEnvelope(event_type=EventType.EXECUTION_COMPLETED, source="test", payload={})
    assert event_to_model(envelope) is None


def test_derive_event_propagates_correlation_chain() -> None:
    project_id = new_project_id()
    parent = model_to_envelope(
        WorkItemChanged(work_item=WorkItem(project_id=project_id, title="t")),
        source="fake-jira",
        project_id=project_id,
        idempotency_key="webhook-1",
    )
    derived = derive_event(
        parent,
        ExecutionRequested(execution=_execution()),
        source="ingestion",
    )
    assert derived.correlation_id == parent.correlation_id
    assert derived.causation_id == parent.event_id
    assert derived.project_id == parent.project_id
    assert derived.source == "ingestion"
    assert derived.idempotency_key is None
