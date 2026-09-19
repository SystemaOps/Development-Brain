"""Phase 1 tests: unified OpenProject ingestion service.

Webhook, bootstrap, and pull share one canonical ingestion path.  These tests
exercise ``OpenProjectIngestionService`` against in-memory reference adapters:

- LIVE mode: diff -> semantic changes -> canonical events, assignment trigger
  only when newly assigned to the brain actor;
- BOOTSTRAP mode: persist + baseline, NO workflow triggers;
- identity resolution idempotency (no duplicates on re-ingestion);
- parent/relation resolution (including two-pass batch resolution);
- attachment reconciliation (metadata + text content via fetcher);
- comments: bootstrap = context, live = HumanFeedbackReceived;
- canonical type/status/priority mapping applied to WorkItems.
"""

from __future__ import annotations

import pytest

from brain.adapters.in_memory.event_bus import InMemoryEventBus
from brain.adapters.in_memory.knowledge_graph import InMemoryKnowledgeGraph
from brain.adapters.in_memory.openproject_snapshot import InMemoryOpenProjectSnapshotStore
from brain.adapters.in_memory.repositories import (
    InMemoryActorRepository,
    InMemoryAttachmentRepository,
    InMemoryCommentRepository,
    InMemoryProjectRepository,
    InMemoryWorkItemRelationRepository,
    InMemoryWorkItemRepository,
)
from brain.adapters.in_memory.work_management import InMemoryWorkManagementIntegrationRepository
from brain.application.document_ingestion import DocumentIngestionService
from brain.application.openproject_ingestion import (
    IngestionMode,
    OpenProjectIngestionService,
)
from brain.application.openproject_mapping import map_human_work_status, map_work_item_type
from brain.application.openproject_parser import OpenProjectWorkItemSnapshot
from brain.domain.common import Priority
from brain.domain.external_reference import ExternalReference
from brain.domain.graph_schema import GraphLabel, RelationType
from brain.domain.projects import Project
from brain.domain.work_item_relations import WorkItemRelationType
from brain.domain.work_items import HumanWorkStatus, WorkItemType


def _service(
    *,
    brain_actor_id: str | None = None,
    document_ingestion: DocumentIngestionService | None = None,
    content_fetcher: object | None = None,
) -> tuple[OpenProjectIngestionService, InMemoryEventBus, InMemoryKnowledgeGraph]:
    projects = InMemoryProjectRepository()
    work_items = InMemoryWorkItemRepository()
    actors = InMemoryActorRepository()
    comments = InMemoryCommentRepository()
    attachments = InMemoryAttachmentRepository()
    relations = InMemoryWorkItemRelationRepository()
    integrations = InMemoryWorkManagementIntegrationRepository()
    snapshots = InMemoryOpenProjectSnapshotStore()
    events = InMemoryEventBus()
    graph = InMemoryKnowledgeGraph()
    service = OpenProjectIngestionService(
        projects=projects,
        work_items=work_items,
        actors=actors,
        comments=comments,
        attachments=attachments,
        relations=relations,
        integrations=integrations,
        snapshots=snapshots,
        graph=graph,
        event_bus=events,
        brain_actor_id=brain_actor_id,
        document_ingestion=document_ingestion,
        content_fetcher=content_fetcher,  # type: ignore[arg-type]
    )
    return service, events, graph


def _snapshot(
    external_id: str,
    *,
    summary: str = "Task",
    description: str = "",
    type_name: str = "Task",
    priority: str = "Normal",
    state: str = "In progress",
    project_id: str | None = "8",
    assignee_id: str | None = None,
    assignee_name: str | None = None,
    parent_id: int | None = None,
    relations: list[dict[str, object]] | None = None,
    attachments: list[dict[str, object]] | None = None,
) -> OpenProjectWorkItemSnapshot:
    return OpenProjectWorkItemSnapshot(
        external_id=external_id,
        summary=summary,
        description=description,
        type=type_name,
        priority=priority,
        state=state,
        project_id=project_id,
        assignee_id=assignee_id,
        assignee_name=assignee_name,
        parent_id=parent_id,
        relations=relations or [],
        attachments=attachments or [],
    )


@pytest.fixture
def seeded_project() -> Project:
    return Project(
        name="op-project",
        external_refs=[
            ExternalReference(provider="openproject", external_id="8", external_type="project")
        ],
    )


async def _seed(service: OpenProjectIngestionService, project: Project) -> None:
    await service._projects.create(project)  # type: ignore[attr-defined]


async def test_gate_live_created_emits_created_event_and_snapshot() -> None:
    service, events, _ = _service()
    project = Project(name="p")
    await _seed(service, project)

    result = await service.ingest_work_item_snapshot(
        _snapshot("43", summary="test"),
        mode=IngestionMode.LIVE,
        source="webhook",
    )
    assert result.created is True
    assert result.changes == []
    assert result.event_type == "work_item_created"

    work_item = await service._work_items.get(result.work_item.id)  # type: ignore[attr-defined]
    assert work_item is not None
    assert work_item.title == "test"
    assert work_item.type == WorkItemType.TASK
    assert work_item.human_work_status == HumanWorkStatus.IN_PROGRESS
    assert work_item.priority == Priority.MEDIUM
    assert any(event.event_type.value == "work_item_created" for event in events.published)
    # Durable baseline saved for future diffs.
    snapshot = await service._snapshots.get("43")  # type: ignore[attr-defined]
    assert snapshot is not None
    assert snapshot.summary == "test"


async def test_gate_live_update_reports_semantic_changes() -> None:
    service, events, _ = _service()
    project = Project(name="p")
    await _seed(service, project)

    first = await service.ingest_work_item_snapshot(
        _snapshot("43", summary="test"),
        mode=IngestionMode.LIVE,
        source="webhook",
    )
    second = await service.ingest_work_item_snapshot(
        _snapshot(
            "43", summary="test", description="updated", assignee_id="6", assignee_name="alice"
        ),
        mode=IngestionMode.LIVE,
        source="webhook",
    )
    assert second.created is False
    assert second.event_type == "work_item_changed"
    assert any(change.value == "description_changed" for change in second.changes)
    assert any(change.value == "assignee_changed" for change in second.changes)
    # Same external id resolves to the same canonical work item.
    assert first.work_item is not None and second.work_item is not None
    assert first.work_item.id == second.work_item.id
    # No duplicates on re-ingestion.
    stored = await service._work_items.find_by_external_ref(  # type: ignore[attr-defined]
        "openproject", "43", "work_package"
    )
    assert stored is not None
    assert stored.description == "updated"
    assert stored.assignee is not None
    assert any(event.event_type.value == "work_item_changed" for event in events.published)


async def test_gate_assignment_triggers_only_when_new() -> None:
    service, events, _ = _service(brain_actor_id="6")
    project = Project(name="p")
    await _seed(service, project)

    # Created with assignee = brain actor -> triggers.
    created = await service.ingest_work_item_snapshot(
        _snapshot("40", summary="task", assignee_id="6", assignee_name="brain"),
        mode=IngestionMode.LIVE,
        source="webhook",
    )
    assert created.assignment_triggered is True
    assert any(event.event_type.value == "work_item_assigned" for event in events.published)

    # Same snapshot again: no assignee change -> no trigger.
    again = await service.ingest_work_item_snapshot(
        _snapshot("40", summary="task", assignee_id="6", assignee_name="brain"),
        mode=IngestionMode.LIVE,
        source="webhook",
    )
    assert again.assignment_triggered is False
    assigned_count = sum(
        1 for event in events.published if event.event_type.value == "work_item_assigned"
    )
    assert assigned_count == 1


async def test_gate_assignment_not_triggered_for_other_assignee() -> None:
    service, events, _ = _service(brain_actor_id="6")
    project = Project(name="p")
    await _seed(service, project)

    result = await service.ingest_work_item_snapshot(
        _snapshot("40", summary="task", assignee_id="7", assignee_name="bob"),
        mode=IngestionMode.LIVE,
        source="webhook",
    )
    assert result.assignment_triggered is False
    assert not any(event.event_type.value == "work_item_assigned" for event in events.published)


async def test_gate_bootstrap_emits_no_workflow_events() -> None:
    service, events, _ = _service(brain_actor_id="6")
    project = Project(name="p")
    await _seed(service, project)

    # Historical state: already assigned to the brain actor.
    result = await service.ingest_work_item_snapshot(
        _snapshot("43", summary="old task", assignee_id="6", assignee_name="brain"),
        mode=IngestionMode.BOOTSTRAP,
        source="bootstrap",
    )
    assert result.created is True
    assert result.assignment_triggered is False
    assert result.event_type is None
    assert events.published == []
    # Work item is still persisted canonically.
    stored = await service._work_items.find_by_external_ref(  # type: ignore[attr-defined]
        "openproject", "43", "work_package"
    )
    assert stored is not None
    assert stored.assignee is not None
    # Durable baseline exists so a later webhook does not look new.
    snapshot = await service._snapshots.get("43")  # type: ignore[attr-defined]
    assert snapshot is not None


async def test_gate_parent_resolution_and_two_pass_batch() -> None:
    service, events, _ = _service()
    project = Project(name="p")
    await _seed(service, project)

    parent = _snapshot("21", summary="parent")
    child = _snapshot("43", summary="child", parent_id=21)

    # Arrival order: child first -> parent unresolved immediately.
    await service.ingest_work_item_snapshot(child, mode=IngestionMode.BOOTSTRAP, source="bootstrap")
    child_stored = await service._work_items.find_by_external_ref(  # type: ignore[attr-defined]
        "openproject", "43", "work_package"
    )
    assert child_stored is not None
    assert child_stored.parent_id is None

    # Pass 1 done; pass 2 resolves the hierarchy regardless of order.
    await service.ingest_work_item_snapshot(
        parent, mode=IngestionMode.BOOTSTRAP, source="bootstrap"
    )
    await service.resolve_relationships([parent, child])

    parent_stored = await service._work_items.find_by_external_ref(  # type: ignore[attr-defined]
        "openproject", "21", "work_package"
    )
    child_stored = await service._work_items.find_by_external_ref(  # type: ignore[attr-defined]
        "openproject", "43", "work_package"
    )
    assert parent_stored is not None
    assert child_stored is not None
    assert child_stored.parent_id == parent_stored.id


async def test_gate_relations_persist_and_project_to_graph() -> None:
    service, events, graph = _service()
    project = Project(name="p")
    await _seed(service, project)

    a = _snapshot("1", summary="a", relations=[{"id": 5, "from": 1, "to": 2, "type": "blocks"}])
    b = _snapshot("2", summary="b")
    await service.ingest_work_item_snapshot(a, mode=IngestionMode.BOOTSTRAP, source="bootstrap")
    await service.ingest_work_item_snapshot(b, mode=IngestionMode.BOOTSTRAP, source="bootstrap")
    await service.resolve_relationships([a, b])

    a_stored = await service._work_items.find_by_external_ref(  # type: ignore[attr-defined]
        "openproject", "1", "work_package"
    )
    b_stored = await service._work_items.find_by_external_ref(  # type: ignore[attr-defined]
        "openproject", "2", "work_package"
    )
    assert a_stored is not None and b_stored is not None

    listed = await service._relations.list_by_work_item(a_stored.id)  # type: ignore[attr-defined]
    assert len(listed) == 1
    assert listed[0].relation_type == WorkItemRelationType.BLOCKS
    assert listed[0].target_work_item_id == b_stored.id

    edges = await graph.find_relations(RelationType.BLOCKS)
    assert len(edges) == 1
    assert edges[0].subject_id == a_stored.id
    assert edges[0].object_id == b_stored.id


async def test_gate_attachment_reconciliation_is_idempotent() -> None:
    service, events, graph = _service()
    project = Project(name="p")
    await _seed(service, project)

    attachments = [
        {
            "id": 3,
            "file_name": "spec.pdf",
            "content_type": "application/pdf",
            "file_size": 1024,
            "download_url": "https://op.example/api/v3/attachments/3/download",
        }
    ]
    first = await service.ingest_work_item_snapshot(
        _snapshot("43", summary="t", attachments=attachments),
        mode=IngestionMode.BOOTSTRAP,
        source="bootstrap",
    )
    second = await service.ingest_work_item_snapshot(
        _snapshot("43", summary="t", attachments=attachments),
        mode=IngestionMode.BOOTSTRAP,
        source="bootstrap",
    )
    assert first.work_item is not None
    assert second.work_item is not None

    stored = await service._attachments.list_by_work_item(first.work_item.id)  # type: ignore[attr-defined]
    assert len(stored) == 1
    assert stored[0].file_name == "spec.pdf"
    assert stored[0].download_url is not None
    assert stored[0].content_ingested is False

    edges = await graph.find_relations(RelationType.HAS_ATTACHMENT)
    assert len(edges) == 1


async def test_gate_attachment_text_content_is_indexed() -> None:
    from brain.adapters.in_memory.repositories import InMemoryDocumentRepository
    from brain.adapters.parsers.entity import NoopEntityExtractor
    from brain.adapters.parsers.markdown import MarkdownParser
    from brain.adapters.parsers.references import ReferenceExtractor
    from brain.adapters.parsers.registry import DefaultParserRegistry

    class _FakeFetcher:
        def __init__(self, content: bytes) -> None:
            self.content = content

        async def fetch(self, url: str) -> bytes:
            return self.content

    documents = InMemoryDocumentRepository()
    registry = DefaultParserRegistry()
    registry.register(MarkdownParser())
    ingestion = DocumentIngestionService(
        documents=documents,
        parser_registry=registry,
        entity_extractor=NoopEntityExtractor(),
        reference_extractor=ReferenceExtractor(),
    )
    service, events, graph = _service(
        document_ingestion=ingestion,
        content_fetcher=_FakeFetcher(b"# Attachment notes\n\nSome text."),
    )
    project = Project(name="p")
    await _seed(service, project)

    result = await service.ingest_work_item_snapshot(
        _snapshot(
            "43",
            summary="t",
            attachments=[
                {
                    "id": 4,
                    "file_name": "notes.md",
                    "content_type": "text/markdown",
                    "file_size": 40,
                    "download_url": "https://op.example/api/v3/attachments/4/download",
                }
            ],
        ),
        mode=IngestionMode.BOOTSTRAP,
        source="bootstrap",
    )
    assert result.work_item is not None
    stored = await service._attachments.list_by_work_item(result.work_item.id)  # type: ignore[attr-defined]
    assert len(stored) == 1
    assert stored[0].content_ingested is True
    indexed = await documents.list_by_project(project.id)
    assert len(indexed) == 1
    assert "Attachment notes" in indexed[0].title


async def test_gate_comment_bootstrap_is_context_only() -> None:
    service, events, _ = _service()
    project = Project(name="p")
    await _seed(service, project)
    result = await service.ingest_work_item_snapshot(
        _snapshot("43", summary="t"),
        mode=IngestionMode.BOOTSTRAP,
        source="bootstrap",
    )
    assert result.work_item is not None

    comment = await service.ingest_comment(
        work_item_id=result.work_item.id,
        external_id="c-1",
        author_name="alice",
        text="historical note",
        mode=IngestionMode.BOOTSTRAP,
    )
    assert comment.kind.value == "context"
    assert not any(
        event.event_type.value == "human_feedback_received" for event in events.published
    )

    # Idempotent: re-ingesting the same comment returns the existing one.
    again = await service.ingest_comment(
        work_item_id=result.work_item.id,
        external_id="c-1",
        author_name="alice",
        text="historical note",
        mode=IngestionMode.BOOTSTRAP,
    )
    assert again.id == comment.id


async def test_gate_comment_live_emits_human_feedback() -> None:
    service, events, _ = _service()
    project = Project(name="p")
    await _seed(service, project)
    result = await service.ingest_work_item_snapshot(
        _snapshot("43", summary="t"),
        mode=IngestionMode.LIVE,
        source="webhook",
    )
    assert result.work_item is not None

    comment = await service.ingest_comment(
        work_item_id=result.work_item.id,
        external_id="c-1",
        author_name="alice",
        text="Please clarify the policy.",
        mode=IngestionMode.LIVE,
        source="webhook",
    )
    assert comment.kind.value == "feedback"
    feedback_events = [
        event for event in events.published if event.event_type.value == "human_feedback_received"
    ]
    assert len(feedback_events) == 1
    assert feedback_events[0].payload["external_comment_id"] == "c-1"
    assert feedback_events[0].payload["feedback"] == "Please clarify the policy."


async def test_gate_work_item_subgraph_projection() -> None:
    service, events, graph = _service()
    project = Project(name="p")
    await _seed(service, project)

    result = await service.ingest_work_item_snapshot(
        _snapshot("43", summary="t", assignee_id="6", assignee_name="alice"),
        mode=IngestionMode.BOOTSTRAP,
        source="bootstrap",
    )
    assert result.work_item is not None

    work_item_entities = await graph.find_entities(GraphLabel.WORK_ITEM)
    assert len(work_item_entities) == 1
    part_of = await graph.find_relations(RelationType.PART_OF)
    assert len(part_of) == 1
    assert part_of[0].subject_id == result.work_item.id
    assert part_of[0].object_id == project.id
    assigned = await graph.find_relations(RelationType.ASSIGNED_TO)
    assert len(assigned) == 1
    assert assigned[0].subject_id == result.work_item.id


async def test_gate_unknown_type_and_status_fall_back() -> None:
    service, _, _ = _service()
    project = Project(name="p")
    await _seed(service, project)

    result = await service.ingest_work_item_snapshot(
        _snapshot("43", summary="t", type_name="MysteryType", state="MysteryStatus"),
        mode=IngestionMode.BOOTSTRAP,
        source="bootstrap",
    )
    assert result.work_item is not None
    stored = await service._work_items.get(result.work_item.id)  # type: ignore[attr-defined]
    assert stored is not None
    assert stored.type == WorkItemType.TASK
    assert stored.human_work_status == HumanWorkStatus.NEW


async def test_gate_mapping_functions() -> None:
    assert map_work_item_type("Bug") == WorkItemType.BUG
    assert map_work_item_type("User story") == WorkItemType.STORY
    assert map_human_work_status("Closed") == HumanWorkStatus.DONE
    assert map_human_work_status("In development") == HumanWorkStatus.IN_PROGRESS
