"""Unified OpenProject ingestion service (Phase 1).

Webhook, bootstrap, and pull converge on one canonical ingestion path:
:meth:`OpenProjectIngestionService.ingest_work_item_snapshot`.

Common responsibilities (bootstrap plan Phase 11):

- identity resolution via ``ExternalReference`` reverse lookup (idempotent);
- ``WorkItem`` persistence with canonical type/status/priority mapping;
- assignee -> canonical ``Actor`` resolution (deterministic provider identity);
- parent/relation resolution (two-pass for batches);
- attachment reconciliation (metadata + download links, text content parsed);
- durable snapshot persistence (baseline for future diffs);
- work-item subgraph projection.

Mode behavior:

- ``BOOTSTRAP``: persist state, build graph, create baseline, **no** workflow
  triggers (an existing task assigned to the Brain must not re-run);
- ``LIVE``: diff old/new snapshot, emit ``SemanticChange[]`` and canonical
  events (``WorkItemCreated`` / ``WorkItemChanged`` / ``WorkItemAssigned``
  only when newly assigned to the brain actor).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from brain.application.document_ingestion import DocumentIngestionService
from brain.application.openproject_mapping import (
    map_human_work_status,
    map_priority,
    map_work_item_type,
)
from brain.application.openproject_parser import (
    OpenProjectWorkItemSnapshot,
    SemanticChange,
    diff_snapshots,
)
from brain.domain.actors import Actor, ActorType
from brain.domain.attachments import Attachment
from brain.domain.comments import Comment, CommentKind
from brain.domain.documents import SourceArtifact
from brain.domain.event_types import (
    FeedbackVerdict,
    HumanFeedbackReceived,
    WorkItemAssigned,
    WorkItemChanged,
    WorkItemCreated,
    model_to_envelope,
)
from brain.domain.events import EventEnvelope, EventType
from brain.domain.external_reference import ExternalReference
from brain.domain.graph_schema import GraphLabel, RelationType
from brain.domain.identity import (
    ActorId,
    ProjectId,
    WorkItemId,
)
from brain.domain.projects import Project
from brain.domain.work_item_relations import (
    WorkItemRelation,
    WorkItemRelationType,
)
from brain.domain.work_items import WorkItem
from brain.domain.work_management import IntegrationMapping, SyncState
from brain.ports.attachment_content import AttachmentContentFetcher
from brain.ports.event_bus import EventBus
from brain.ports.knowledge_graph import (
    GraphEntity,
    GraphRelation,
    KnowledgeGraphRepository,
)
from brain.ports.openproject_snapshot import OpenProjectSnapshotStore
from brain.ports.repositories import (
    ActorRepository,
    AttachmentRepository,
    CommentRepository,
    ProjectRepository,
    WorkItemRelationRepository,
    WorkItemRepository,
)
from brain.ports.work_management_repo import WorkManagementIntegrationRepository

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


class IngestionMode(StrEnum):
    BOOTSTRAP = "BOOTSTRAP"
    LIVE = "LIVE"


@dataclass
class OpenProjectIngestionResult:
    """Outcome of one canonical ingestion call."""

    work_item: WorkItem | None = None
    created: bool = False
    changes: list[SemanticChange] = field(default_factory=list)
    event_type: str | None = None
    assignment_triggered: bool = False
    snapshot_saved: bool = False
    comments_ingested: int = 0
    attachments_ingested: int = 0
    relations_ingested: int = 0


class OpenProjectIngestionService:
    """One canonical ingestion path for webhook / bootstrap / pull."""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        work_items: WorkItemRepository,
        actors: ActorRepository,
        comments: CommentRepository,
        attachments: AttachmentRepository,
        relations: WorkItemRelationRepository,
        integrations: WorkManagementIntegrationRepository,
        snapshots: OpenProjectSnapshotStore,
        graph: KnowledgeGraphRepository,
        event_bus: EventBus,
        brain_actor_id: str | None = None,
        document_ingestion: DocumentIngestionService | None = None,
        content_fetcher: AttachmentContentFetcher | None = None,
    ) -> None:
        self._projects = projects
        self._work_items = work_items
        self._actors = actors
        self._comments = comments
        self._attachments = attachments
        self._relations = relations
        self._integrations = integrations
        self._snapshots = snapshots
        self._graph = graph
        self._event_bus = event_bus
        self._brain_actor_id = brain_actor_id
        self._document_ingestion = document_ingestion
        self._content_fetcher = content_fetcher

    # --- project ingestion (Phase 2.2) -------------------------------------

    async def upsert_project(
        self,
        *,
        external_id: str,
        name: str,
        description: str = "",
        parent_external_id: str | None = None,
        project_id: ProjectId | None = None,
    ) -> Project:
        """Upsert a canonical project resolved from a provider project.

        Identity is the ``(openproject, project, external_id)`` external
        reference (never the provider name).  The parent is resolved via the
        reverse lookup, so a parent arriving later is fixed by a second pass.
        """
        project = None
        if project_id is not None:
            project = await self._projects.get(project_id)
        if project is None:
            project = await self._projects.find_by_external_ref(
                "openproject", external_id, "project"
            )

        ref = ExternalReference(
            provider="openproject",
            external_id=external_id,
            external_type="project",
        )
        parent_id: ProjectId | None = None
        if parent_external_id:
            parent = await self._projects.find_by_external_ref(
                "openproject", parent_external_id, "project"
            )
            if parent is not None:
                parent_id = parent.id

        if project is None:
            project = Project(
                name=name or f"OpenProject {external_id}",
                description=description or None,
                parent_id=parent_id,
                external_refs=[ref],
            )
            created = await self._projects.create(project)
            await self._upsert_project_node(created)
            return created

        updated = project.model_copy(
            update={
                "name": name or project.name,
                "description": description or project.description,
                "parent_id": parent_id or project.parent_id,
            }
        )
        if ref not in updated.external_refs:
            updated.external_refs = [*updated.external_refs, ref]
        if updated != project:
            stored = await self._projects.update(updated)
            await self._upsert_project_node(stored)
            return stored
        await self._upsert_project_node(project)
        return project

    async def _upsert_project_node(self, project: Project) -> None:
        await self._graph.upsert_entities(
            [
                GraphEntity(
                    id=project.id,
                    label=GraphLabel.PROJECT,
                    project_id=project.id,
                    properties={"name": project.name},
                )
            ]
        )
        if project.parent_id is not None:
            await self._graph.upsert_relations(
                [
                    GraphRelation(
                        subject_id=project.parent_id,
                        relation_type=RelationType.PARENT_OF,
                        object_id=project.id,
                    )
                ]
            )

    # --- work item ingestion ----------------------------------------------

    async def ingest_work_item_snapshot(
        self,
        snapshot: OpenProjectWorkItemSnapshot,
        *,
        mode: IngestionMode,
        source: str,
        correlation_id: uuid.UUID | None = None,
        project_id: ProjectId | None = None,
        provider_action: str | None = None,
    ) -> OpenProjectIngestionResult:
        """Persist one normalized work-item snapshot canonically (doc Phase 11).

        ``mode=BOOTSTRAP`` never triggers workflows; ``mode=LIVE`` diffs the
        snapshot against the durable baseline and emits canonical events.

        ``provider_action`` (e.g. ``work_package:created``) is honored when the
        provider reports the event: the emitted event type and the assignment
        trigger follow the provider action rather than whether the brain knew
        the entity before (webhook semantics).
        """
        result = OpenProjectIngestionResult()
        previous = await self._snapshots.get(snapshot.external_id)
        changes = diff_snapshots(previous, snapshot)

        project = await self._resolve_project(snapshot, project_id)
        work_item = None
        if project is not None:
            work_item, created = await self._find_or_create_work_item(snapshot, project)
            if work_item is not None:
                result.created = created
                result.work_item = work_item
                result.changes = changes
                await self._apply_snapshot(work_item, snapshot)
                await self._resolve_parent(work_item, snapshot)
                result.relations_ingested += await self._resolve_relations(work_item, snapshot)
                result.attachments_ingested += await self._reconcile_attachments(
                    work_item, snapshot
                )
                await self._project_subgraph(work_item)

        await self._snapshots.save(snapshot)
        result.snapshot_saved = True

        if mode == IngestionMode.BOOTSTRAP:
            # Persist + baseline only; historical state must not trigger work.
            return result

        if work_item is not None and project is not None:
            created_event = self._event_is_created(result.created, provider_action)
            envelope = self._build_work_item_envelope(
                work_item,
                snapshot,
                changes,
                created=created_event,
                source=source,
                project_id=project,
                correlation_id=correlation_id,
            )
            await self._event_bus.publish(envelope)
            result.event_type = envelope.event_type.value
            if self._should_trigger_assignment(snapshot, changes, result.created, provider_action):
                await self._publish_assignment(work_item, snapshot, source, correlation_id)
                result.assignment_triggered = True
        else:
            # Compat fallback: no canonical project/work item could be
            # resolved; still report the provider fact as a generic event.
            envelope = EventEnvelope(
                event_type=(
                    EventType.WORK_ITEM_CREATED
                    if self._event_is_created(result.created, provider_action)
                    else EventType.WORK_ITEM_CHANGED
                ),
                correlation_id=correlation_id or uuid.uuid4(),
                source=source,
                payload={
                    "provider": "openproject",
                    "external_id": snapshot.external_id,
                    "subject": snapshot.summary,
                    "status": snapshot.state,
                    "assignee": snapshot.assignee_id,
                    "changes": [change.value for change in changes],
                    "snapshot": _snapshot_payload(snapshot),
                },
            )
            await self._event_bus.publish(envelope)
            result.event_type = envelope.event_type.value

        return result

    async def _resolve_project(
        self,
        snapshot: OpenProjectWorkItemSnapshot,
        project_id: ProjectId | None,
    ) -> ProjectId | None:
        if project_id is not None:
            project = await self._projects.get(project_id)
            return project_id if project is not None else None
        if snapshot.project_id:
            project = await self._projects.find_by_external_ref(
                "openproject", snapshot.project_id, "project"
            )
            if project is not None:
                return project.id
        projects = await self._projects.list()
        return projects[0].id if projects else None

    async def _find_or_create_work_item(
        self,
        snapshot: OpenProjectWorkItemSnapshot,
        project_id: ProjectId,
    ) -> tuple[WorkItem, bool]:
        existing = await self._work_items.find_by_external_ref(
            "openproject", snapshot.external_id, "work_package"
        )
        if existing is not None:
            return existing, False

        ref = ExternalReference(
            provider="openproject",
            external_id=snapshot.external_id,
            external_type="work_package",
        )
        work_item = WorkItem(
            project_id=project_id,
            title=snapshot.summary or f"OpenProject {snapshot.external_id}",
            description=snapshot.description,
            external_refs=[ref],
        )
        created = await self._work_items.create(work_item)
        await self._integrations.save_mapping(
            IntegrationMapping(
                work_item_id=created.id,
                provider="openproject",
                external_id=snapshot.external_id,
                sync_state=SyncState.SYNCED,
                last_synced_at=datetime.now(UTC),
            )
        )
        return created, True

    async def _apply_snapshot(
        self, work_item: WorkItem, snapshot: OpenProjectWorkItemSnapshot
    ) -> None:
        work_item.title = snapshot.summary or work_item.title
        work_item.description = snapshot.description or work_item.description
        work_item.type = map_work_item_type(snapshot.type)
        work_item.human_work_status = map_human_work_status(snapshot.state)
        work_item.priority = map_priority(snapshot.priority)
        assignee = await self._resolve_assignee(snapshot)
        if assignee is not None:
            work_item.assignee = assignee
        await self._work_items.update(work_item)

    async def _resolve_assignee(self, snapshot: OpenProjectWorkItemSnapshot) -> ActorId | None:
        if not snapshot.assignee_id:
            return None
        actor_id = ActorId(uuid.uuid5(_NAMESPACE, f"openproject:user:{snapshot.assignee_id}"))
        actor = await self._actors.get(actor_id)
        if actor is None:
            actor = Actor(
                id=actor_id,
                actor_type=ActorType.HUMAN,
                display_name=snapshot.assignee_name or snapshot.assignee_id,
            )
            await self._actors.create(actor)
        return actor_id

    # --- two-pass relationship resolution (Phase 1.3) ---------------------

    async def _resolve_parent(
        self,
        work_item: WorkItem,
        snapshot: OpenProjectWorkItemSnapshot,
    ) -> None:
        if not snapshot.parent_id:
            return
        parent = await self._work_items.find_by_external_ref(
            "openproject", str(snapshot.parent_id), "work_package"
        )
        if parent is not None and parent.id != work_item.id:
            work_item.parent_id = parent.id
            await self._work_items.update(work_item)

    async def _resolve_relations(
        self,
        work_item: WorkItem,
        snapshot: OpenProjectWorkItemSnapshot,
    ) -> int:
        ingested = 0
        for raw in snapshot.relations:
            target_id = raw.get("target_id") or raw.get("to")
            relation_type = raw.get("relation_type") or raw.get("type")
            if not target_id or not relation_type:
                continue
            mapped = _map_relation_type(str(relation_type))
            if mapped is None:
                continue
            # OpenProject lists a relation on the work package that owns it
            # (the ``from`` side); fall back to the ingested work item when the
            # provider omits the source.
            source_id = raw.get("source_id") or raw.get("from")
            if source_id is not None and str(source_id) != snapshot.external_id:
                source = await self._work_items.find_by_external_ref(
                    "openproject", str(source_id), "work_package"
                )
                if source is None:
                    continue
                source_work_item_id = source.id
            else:
                source_work_item_id = work_item.id
            target = await self._work_items.find_by_external_ref(
                "openproject", str(target_id), "work_package"
            )
            if target is None or target.id == source_work_item_id:
                continue
            await self._relations.create(
                WorkItemRelation(
                    source_work_item_id=source_work_item_id,
                    target_work_item_id=target.id,
                    relation_type=mapped,
                    external_refs=[
                        ExternalReference(
                            provider="openproject",
                            external_id=str(raw.get("id") or f"{source_work_item_id}:{target_id}"),
                            external_type="relation",
                        )
                    ],
                )
            )
            ingested += 1
        return ingested

    async def resolve_relationships(
        self,
        snapshots: list[OpenProjectWorkItemSnapshot],
    ) -> None:
        """Pass 2 for bootstrap batches: resolve parents/relations after all
        entities exist, regardless of arrival order (doc Phase 4)."""
        for snapshot in snapshots:
            work_item = await self._work_items.find_by_external_ref(
                "openproject", snapshot.external_id, "work_package"
            )
            if work_item is None:
                continue
            await self._resolve_parent(work_item, snapshot)
            await self._resolve_relations(work_item, snapshot)
            await self._project_subgraph(work_item)

    # --- attachments (Phase 1.4) -------------------------------------------

    async def _reconcile_attachments(
        self,
        work_item: WorkItem,
        snapshot: OpenProjectWorkItemSnapshot,
    ) -> int:
        ingested = 0
        for raw in snapshot.attachments:
            external_id = str(raw.get("id") or "")
            if not external_id:
                continue
            await self._reconcile_attachment(
                raw,
                work_item,
                external_id=external_id,
            )
            ingested += 1
        return ingested

    async def _reconcile_attachment(
        self,
        raw: dict[str, object],
        work_item: WorkItem,
        *,
        external_id: str,
    ) -> Attachment:
        existing = await self._attachments.find_by_external_ref(
            "openproject", external_id, "attachment"
        )
        if existing is not None:
            updated = existing.model_copy(
                update={
                    "file_name": str(raw.get("file_name") or existing.file_name),
                    "content_type": str(raw.get("content_type") or existing.content_type),
                    "file_size": raw.get("file_size", existing.file_size),
                    "download_url": str(raw.get("download_url") or "") or existing.download_url,
                }
            )
            if updated != existing:
                await self._attachments.create(updated)
            return updated

        attachment = Attachment(
            work_item_id=work_item.id,
            file_name=str(raw.get("file_name") or f"attachment-{external_id}"),
            content_type=str(raw.get("content_type") or ""),
            file_size=_as_int(raw.get("file_size")),
            download_url=str(raw.get("download_url") or "") or None,
            external_refs=[
                ExternalReference(
                    provider="openproject",
                    external_id=external_id,
                    external_type="attachment",
                )
            ],
        )
        await self._attachments.create(attachment)

        fetcher = self._content_fetcher
        document_ingestion = self._document_ingestion
        if (
            fetcher is not None
            and document_ingestion is not None
            and attachment.download_url
            and _is_text_attachment(attachment.content_type)
        ):
            await self._ingest_attachment_content(attachment, work_item.project_id)

        await self._upsert_attachment_edges(attachment)
        return attachment

    async def _ingest_attachment_content(
        self,
        attachment: Attachment,
        project_id: ProjectId,
    ) -> None:
        fetcher = self._content_fetcher
        document_ingestion = self._document_ingestion
        if fetcher is None or document_ingestion is None or attachment.download_url is None:
            return
        try:
            content = await fetcher.fetch(attachment.download_url)
        except Exception:  # noqa: BLE001
            logger.warning(
                "attachment content fetch failed: %s (%s)",
                attachment.download_url,
                attachment.file_name,
                exc_info=True,
            )
            return
        artifact = SourceArtifact(
            source_uri=attachment.download_url,
            provider="openproject",
            mime_type=attachment.content_type or "text/plain",
            file_name=attachment.file_name,
            content=content,
        )
        await document_ingestion.ingest(
            artifact,
            project_id=project_id,
        )
        await self._attachments.create(attachment.model_copy(update={"content_ingested": True}))

    async def _upsert_attachment_edges(self, attachment: Attachment) -> None:
        await self._graph.upsert_entities(
            [
                GraphEntity(
                    id=attachment.id,
                    label=GraphLabel.ATTACHMENT,
                    project_id=None,
                    properties={
                        "file_name": attachment.file_name,
                        "content_type": attachment.content_type,
                    },
                )
            ]
        )
        await self._graph.upsert_relations(
            [
                GraphRelation(
                    subject_id=attachment.work_item_id,
                    relation_type=RelationType.HAS_ATTACHMENT,
                    object_id=attachment.id,
                )
            ]
        )

    # --- comments (Phase 1.5) -----------------------------------------------

    async def ingest_comment(
        self,
        *,
        work_item_id: WorkItemId | None,
        external_id: str,
        author_name: str,
        text: str,
        created_at: datetime | None = None,
        mode: IngestionMode,
        source: str = "openproject.ingestion",
        correlation_id: uuid.UUID | None = None,
    ) -> Comment:
        """Ingest one provider comment.

        BOOTSTRAP stores the comment as context only; LIVE comments normalize
        to ``HumanFeedbackReceived`` and may resume a waiting workflow.
        """
        existing = await self._comments.find_by_external_ref("openproject", external_id, "activity")
        if existing is not None:
            return existing

        comment: Comment | None = None
        if work_item_id is not None:
            comment = Comment(
                work_item_id=work_item_id,
                author_name=author_name,
                text=text,
                kind=CommentKind.CONTEXT
                if mode == IngestionMode.BOOTSTRAP
                else CommentKind.FEEDBACK,
                created_at=created_at or datetime.now(UTC),
                external_refs=[
                    ExternalReference(
                        provider="openproject",
                        external_id=external_id,
                        external_type="activity",
                    )
                ],
            )
            await self._comments.create(comment)

            await self._graph.upsert_entities(
                [
                    GraphEntity(
                        id=comment.id,
                        label=GraphLabel.COMMENT,
                        project_id=None,
                        properties={"text": comment.text[:500]},
                    )
                ]
            )
            await self._graph.upsert_relations(
                [
                    GraphRelation(
                        subject_id=comment.id,
                        relation_type=RelationType.COMMENT_ON,
                        object_id=work_item_id,
                    )
                ]
            )

        if mode == IngestionMode.LIVE:
            await self._event_bus.publish(
                model_to_envelope(
                    HumanFeedbackReceived(
                        work_item_id=work_item_id,
                        author=author_name,
                        provider="openproject",
                        external_comment_id=external_id,
                        verdict=FeedbackVerdict.NOTE,
                        feedback=text,
                    ),
                    source=source,
                    correlation_id=correlation_id,
                )
            )
        if comment is None:
            return Comment(
                work_item_id=WorkItemId(uuid.uuid4()),
                author_name=author_name,
                text=text,
                kind=CommentKind.CONTEXT,
                created_at=created_at or datetime.now(UTC),
            )
        return comment

    # --- live events --------------------------------------------------------

    def _build_work_item_envelope(
        self,
        work_item: WorkItem,
        snapshot: OpenProjectWorkItemSnapshot,
        changes: list[SemanticChange],
        *,
        created: bool,
        source: str,
        project_id: ProjectId,
        correlation_id: uuid.UUID | None,
    ) -> EventEnvelope:
        event = (
            WorkItemCreated(work_item=work_item)
            if created
            else WorkItemChanged(work_item=work_item)
        )
        envelope = model_to_envelope(
            event,
            source=source,
            project_id=project_id,
            correlation_id=correlation_id,
        )
        envelope.payload["changes"] = [change.value for change in changes]
        envelope.payload["snapshot"] = _snapshot_payload(snapshot)
        envelope.payload["external_id"] = snapshot.external_id
        return envelope

    async def _publish_assignment(
        self,
        work_item: WorkItem,
        snapshot: OpenProjectWorkItemSnapshot,
        source: str,
        correlation_id: uuid.UUID | None,
    ) -> None:
        await self._event_bus.publish(
            model_to_envelope(
                WorkItemAssigned(
                    work_item_id=work_item.id,
                    external_actor_id=snapshot.assignee_id,
                ),
                source=source,
                correlation_id=correlation_id,
            )
        )

    def _should_trigger_assignment(
        self,
        snapshot: OpenProjectWorkItemSnapshot,
        changes: list[SemanticChange],
        created: bool,
        provider_action: str | None,
    ) -> bool:
        if not self._brain_actor_id:
            return False
        if not snapshot.assignee_id or snapshot.assignee_id != str(self._brain_actor_id):
            return False
        if provider_action is not None:
            newly_assigned = provider_action == "work_package:created"
        else:
            newly_assigned = created
        if newly_assigned:
            return True
        return any(change == SemanticChange.ASSIGNEE_CHANGED for change in changes)

    def _event_is_created(self, created: bool, provider_action: str | None) -> bool:
        if provider_action is not None:
            return provider_action == "work_package:created"
        return created

    # --- graph projection (Phase 1.6) ---------------------------------------

    async def _project_subgraph(self, work_item: WorkItem) -> None:
        entities: list[GraphEntity] = []
        relations: list[GraphRelation] = []

        entities.append(
            GraphEntity(
                id=work_item.id,
                label=GraphLabel.WORK_ITEM,
                project_id=work_item.project_id,
                properties={
                    "title": work_item.title,
                    "type": _as_str(work_item.type),
                    "human_work_status": _as_str(work_item.human_work_status),
                },
            )
        )
        relations.append(
            GraphRelation(
                subject_id=work_item.id,
                relation_type=RelationType.PART_OF,
                object_id=work_item.project_id,
            )
        )

        project = await self._projects.get(work_item.project_id)
        if project is not None:
            entities.append(
                GraphEntity(
                    id=project.id,
                    label=GraphLabel.PROJECT,
                    project_id=project.id,
                    properties={"name": project.name},
                )
            )

        if work_item.parent_id is not None:
            relations.append(
                GraphRelation(
                    subject_id=work_item.id,
                    relation_type=RelationType.PARENT_OF,
                    object_id=work_item.parent_id,
                )
            )

        for relation in await self._relations.list_by_work_item(work_item.id):
            graph_type = _map_graph_relation(relation.relation_type)
            if graph_type is None:
                continue
            relations.append(
                GraphRelation(
                    subject_id=relation.source_work_item_id,
                    relation_type=graph_type,
                    object_id=relation.target_work_item_id,
                )
            )

        if work_item.assignee is not None:
            entities.append(
                GraphEntity(
                    id=work_item.assignee,
                    label=GraphLabel.ACTOR,
                    project_id=work_item.project_id,
                    properties={"actor_type": "human"},
                )
            )
            relations.append(
                GraphRelation(
                    subject_id=work_item.id,
                    relation_type=RelationType.ASSIGNED_TO,
                    object_id=work_item.assignee,
                )
            )

        await self._graph.upsert_entities(entities)
        await self._graph.upsert_relations(relations)


# --- helpers ----------------------------------------------------------------


def _snapshot_payload(snapshot: OpenProjectWorkItemSnapshot) -> dict[str, object]:
    return {
        "type": snapshot.type,
        "priority": snapshot.priority,
        "closed": snapshot.closed,
        "project_id": snapshot.project_id,
        "project_name": snapshot.project_name,
        "assignee_name": snapshot.assignee_name,
        "parent_id": snapshot.parent_id,
        "attachments": snapshot.attachments,
        "relations": snapshot.relations,
        "activities_url": snapshot.activities_url,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
    }


def _map_relation_type(raw: str) -> WorkItemRelationType | None:
    mapping: dict[str, WorkItemRelationType] = {
        "blocks": WorkItemRelationType.BLOCKS,
        "relates": WorkItemRelationType.RELATES_TO,
        "relates_to": WorkItemRelationType.RELATES_TO,
        "precedes": WorkItemRelationType.PRECEDES,
        "follows": WorkItemRelationType.FOLLOWS,
    }
    return mapping.get(raw.strip().lower())


def _map_graph_relation(relation_type: WorkItemRelationType) -> RelationType | None:
    mapping: dict[WorkItemRelationType, RelationType] = {
        WorkItemRelationType.PARENT_OF: RelationType.PARENT_OF,
        WorkItemRelationType.BLOCKS: RelationType.BLOCKS,
        WorkItemRelationType.RELATES_TO: RelationType.RELATES_TO,
        WorkItemRelationType.PRECEDES: RelationType.PRECEDES,
        WorkItemRelationType.FOLLOWS: RelationType.FOLLOWS,
    }
    return mapping.get(relation_type)


def _is_text_attachment(content_type: str) -> bool:
    lowered = content_type.strip().lower()
    return lowered.startswith("text/") or lowered in {
        "application/json",
        "application/yaml",
        "application/x-yaml",
    }


def _as_str(value: object) -> str:
    return str(getattr(value, "value", value))


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


__all__ = ["IngestionMode", "OpenProjectIngestionResult", "OpenProjectIngestionService"]
