"""Phase 0 gate tests: domain & persistence foundations for bootstrap + pull.

Covers the durable foundations added before the ingestion service exists:
``Project.parent_id`` + project hierarchy, canonical ``Comment``/``Attachment``
entities, ``work_item_relations``, the durable OpenProject snapshot store, the
provider sync watermark, bootstrap state, external-reference reverse lookup,
and the OpenProject type/status mapping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from brain.adapters.in_memory.repositories import (
    InMemoryAttachmentRepository,
    InMemoryCommentRepository,
    InMemoryProjectRepository,
    InMemoryWorkItemRelationRepository,
    InMemoryWorkItemRepository,
)
from brain.adapters.postgresql.database import create_repositories
from brain.adapters.postgresql.openproject_snapshot import PostgresOpenProjectSnapshotStore
from brain.application.openproject_mapping import (
    map_human_work_status,
    map_human_work_status_or_none,
    map_work_item_type,
    map_work_item_type_or_none,
)
from brain.application.openproject_parser import OpenProjectWorkItemSnapshot
from brain.domain.attachments import Attachment
from brain.domain.bootstrap_state import BootstrapStage, BootstrapStatus, ProviderBootstrapState
from brain.domain.comments import Comment, CommentKind
from brain.domain.external_reference import ExternalReference
from brain.domain.projects import Project
from brain.domain.work_item_relations import WorkItemRelation, WorkItemRelationType
from brain.domain.work_items import HumanWorkStatus, WorkItem, WorkItemType
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/brain_test"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)

POSTGRES_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/brain_test"


# --- Project hierarchy (0.2) ----------------------------------------------


async def test_gate_project_parent_id_persists() -> None:
    from brain.adapters.postgresql.config import DatabaseSettings
    from brain.adapters.postgresql.database import async_session_factory, create_async_engine

    engine = create_async_engine(DatabaseSettings(url=POSTGRES_URL))
    try:
        async with engine.begin() as conn:
            from brain.adapters.postgresql.tables import Base

            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_session_factory(engine)
        async with factory() as session:
            repos = create_repositories(session)
            parent = Project(name="parent")
            await repos.projects.create(parent)
            child = Project(name="child", parent_id=parent.id)
            await repos.projects.create(child)
            await session.commit()

        async with factory() as session:
            repos = create_repositories(session)
            stored = await repos.projects.get(child.id)
            assert stored is not None
            assert stored.parent_id == parent.id
    finally:
        await engine.dispose()


# --- Comments and attachments (0.1) ----------------------------------------


async def test_gate_comment_persists_and_lists_by_work_item() -> None:
    from brain.adapters.postgresql.config import DatabaseSettings
    from brain.adapters.postgresql.database import async_session_factory, create_async_engine

    engine = create_async_engine(DatabaseSettings(url=POSTGRES_URL))
    try:
        async with engine.begin() as conn:
            from brain.adapters.postgresql.tables import Base

            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_session_factory(engine)
        project = Project(name="p")
        work_item = WorkItem(project_id=project.id, title="t")
        comment = Comment(
            work_item_id=work_item.id,
            author_name="alice",
            text="hello",
            kind=CommentKind.FEEDBACK,
            external_refs=[
                ExternalReference(
                    provider="openproject", external_id="42", external_type="activity"
                )
            ],
        )
        async with factory() as session:
            repos = create_repositories(session)
            await repos.projects.create(project)
            await repos.work_items.create(work_item)
            await repos.comments.create(comment)
            await session.commit()

        async with factory() as session:
            repos = create_repositories(session)
            stored = await repos.comments.get(comment.id)
            assert stored is not None
            assert stored.text == "hello"
            assert stored.kind == CommentKind.FEEDBACK
            assert stored.external_refs[0].external_id == "42"
            found = await repos.comments.find_by_external_ref("openproject", "42")
            assert found is not None
            assert found.id == comment.id
            by_work_item = await repos.comments.list_by_work_item(work_item.id)
            assert [c.id for c in by_work_item] == [comment.id]
    finally:
        await engine.dispose()


async def test_gate_attachment_persists_and_is_idempotent_by_external_ref() -> None:
    from brain.adapters.postgresql.config import DatabaseSettings
    from brain.adapters.postgresql.database import async_session_factory, create_async_engine

    engine = create_async_engine(DatabaseSettings(url=POSTGRES_URL))
    try:
        async with engine.begin() as conn:
            from brain.adapters.postgresql.tables import Base

            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_session_factory(engine)
        project = Project(name="p")
        work_item = WorkItem(project_id=project.id, title="t")
        attachment = Attachment(
            work_item_id=work_item.id,
            file_name="spec.pdf",
            content_type="application/pdf",
            file_size=1024,
            download_url="https://op.example/api/v3/attachments/7/download",
            external_refs=[
                ExternalReference(
                    provider="openproject", external_id="7", external_type="attachment"
                )
            ],
        )
        async with factory() as session:
            repos = create_repositories(session)
            await repos.projects.create(project)
            await repos.work_items.create(work_item)
            await repos.attachments.create(attachment)
            await session.commit()

        async with factory() as session:
            repos = create_repositories(session)
            stored = await repos.attachments.get(attachment.id)
            assert stored is not None
            assert stored.download_url is not None
            assert stored.content_ingested is False
            found = await repos.attachments.find_by_external_ref("openproject", "7")
            assert found is not None
            assert found.id == attachment.id
    finally:
        await engine.dispose()


# --- Work-item relations (0.3) ---------------------------------------------


async def test_gate_work_item_relation_persists_and_upserts() -> None:
    from brain.adapters.postgresql.config import DatabaseSettings
    from brain.adapters.postgresql.database import async_session_factory, create_async_engine

    engine = create_async_engine(DatabaseSettings(url=POSTGRES_URL))
    try:
        async with engine.begin() as conn:
            from brain.adapters.postgresql.tables import Base

            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_session_factory(engine)
        project = Project(name="p")
        parent = WorkItem(project_id=project.id, title="parent")
        child = WorkItem(project_id=project.id, title="child")
        relation = WorkItemRelation(
            source_work_item_id=parent.id,
            target_work_item_id=child.id,
            relation_type=WorkItemRelationType.PARENT_OF,
        )
        async with factory() as session:
            repos = create_repositories(session)
            await repos.projects.create(project)
            await repos.work_items.create(parent)
            await repos.work_items.create(child)
            await repos.work_item_relations.create(relation)
            await session.commit()

        async with factory() as session:
            repos = create_repositories(session)
            listed = await repos.work_item_relations.list_by_work_item(parent.id)
            assert [r.id for r in listed] == [relation.id]
            assert listed[0].relation_type == WorkItemRelationType.PARENT_OF
            # Upsert must not create a duplicate for the same triple.
            await repos.work_item_relations.create(relation)
            await session.commit()

        async with factory() as session:
            repos = create_repositories(session)
            listed = await repos.work_item_relations.list_by_work_item(child.id)
            assert len(listed) == 1
    finally:
        await engine.dispose()


# --- Durable snapshot store (0.5) ------------------------------------------


async def test_gate_snapshot_store_survives_restart() -> None:
    from brain.adapters.postgresql.config import DatabaseSettings
    from brain.adapters.postgresql.database import async_session_factory, create_async_engine

    engine = create_async_engine(DatabaseSettings(url=POSTGRES_URL))
    try:
        async with engine.begin() as conn:
            from brain.adapters.postgresql.tables import Base

            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_session_factory(engine)
        snapshot = OpenProjectWorkItemSnapshot(
            external_id="43",
            summary="test",
            state="In progress",
            assignee_id="6",
            attachments=[{"id": 3, "file_name": "a.txt"}],
        )
        async with factory() as session:
            store = PostgresOpenProjectSnapshotStore(session)
            await store.save(snapshot)
            await session.commit()

        # New session = simulated restart.
        async with factory() as session:
            store = PostgresOpenProjectSnapshotStore(session)
            loaded = await store.get("43")
            assert loaded is not None
            assert loaded.summary == "test"
            assert loaded.assignee_id == "6"
            assert loaded.attachments == [{"id": 3, "file_name": "a.txt"}]
    finally:
        await engine.dispose()


# --- Sync watermark (0.6) ---------------------------------------------------


async def test_gate_sync_watermark_get_or_create_and_save() -> None:
    from brain.adapters.postgresql.config import DatabaseSettings
    from brain.adapters.postgresql.database import async_session_factory, create_async_engine

    engine = create_async_engine(DatabaseSettings(url=POSTGRES_URL))
    try:
        async with engine.begin() as conn:
            from brain.adapters.postgresql.tables import Base

            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_session_factory(engine)
        async with factory() as session:
            repos = create_repositories(session)
            watermark = await repos.sync_watermarks.get_or_create("openproject", "work_items:8")
            assert watermark.last_synced_at is None
            watermark.last_synced_at = datetime.now(UTC) - timedelta(minutes=5)
            watermark.last_external_id = "99"
            await repos.sync_watermarks.save(watermark)
            await session.commit()

        async with factory() as session:
            repos = create_repositories(session)
            loaded = await repos.sync_watermarks.get_or_create("openproject", "work_items:8")
            assert loaded.last_synced_at is not None
            assert loaded.last_external_id == "99"
    finally:
        await engine.dispose()


# --- Bootstrap state (0.7) --------------------------------------------------


async def test_gate_bootstrap_state_resume_checkpoint() -> None:
    from brain.adapters.postgresql.config import DatabaseSettings
    from brain.adapters.postgresql.database import async_session_factory, create_async_engine

    engine = create_async_engine(DatabaseSettings(url=POSTGRES_URL))
    try:
        async with engine.begin() as conn:
            from brain.adapters.postgresql.tables import Base

            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_session_factory(engine)
        project = Project(name="p")
        state = ProviderBootstrapState(
            project_id=project.id,
            provider="openproject",
            status=BootstrapStatus.INGESTING,
            stage=BootstrapStage.FETCH_WORK_ITEMS,
            last_page=3,
            items_processed=75,
        )
        async with factory() as session:
            repos = create_repositories(session)
            await repos.projects.create(project)
            await repos.bootstrap_states.save(state)
            await session.commit()

        async with factory() as session:
            repos = create_repositories(session)
            loaded = await repos.bootstrap_states.get(project.id, "openproject")
            assert loaded is not None
            assert loaded.status == BootstrapStatus.INGESTING
            assert loaded.last_page == 3
            assert loaded.items_processed == 75
    finally:
        await engine.dispose()


# --- External-reference reverse lookup (0.9) --------------------------------


async def test_gate_external_ref_reverse_lookup() -> None:
    from brain.adapters.postgresql.config import DatabaseSettings
    from brain.adapters.postgresql.database import async_session_factory, create_async_engine

    engine = create_async_engine(DatabaseSettings(url=POSTGRES_URL))
    try:
        async with engine.begin() as conn:
            from brain.adapters.postgresql.tables import Base

            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_session_factory(engine)
        project = Project(
            name="p",
            external_refs=[
                ExternalReference(provider="openproject", external_id="8", external_type="project")
            ],
        )
        work_item = WorkItem(
            project_id=project.id,
            title="t",
            external_refs=[
                ExternalReference(
                    provider="openproject", external_id="43", external_type="work_package"
                )
            ],
        )
        async with factory() as session:
            repos = create_repositories(session)
            await repos.projects.create(project)
            await repos.work_items.create(work_item)
            await session.commit()

        async with factory() as session:
            repos = create_repositories(session)
            found_project = await repos.projects.find_by_external_ref("openproject", "8")
            assert found_project is not None
            assert found_project.id == project.id
            found_work_item = await repos.work_items.find_by_external_ref("openproject", "43")
            assert found_work_item is not None
            assert found_work_item.id == work_item.id
            missing = await repos.work_items.find_by_external_ref("openproject", "999")
            assert missing is None
    finally:
        await engine.dispose()


# --- In-memory reference behavior -------------------------------------------


async def test_gate_in_memory_reverse_lookup_and_relations() -> None:
    projects = InMemoryProjectRepository()
    work_items = InMemoryWorkItemRepository()
    comments = InMemoryCommentRepository()
    attachments = InMemoryAttachmentRepository()
    relations = InMemoryWorkItemRelationRepository()

    project = Project(
        name="p",
        external_refs=[
            ExternalReference(provider="openproject", external_id="8", external_type="project")
        ],
    )
    parent = WorkItem(
        project_id=project.id,
        title="parent",
        external_refs=[
            ExternalReference(
                provider="openproject", external_id="21", external_type="work_package"
            )
        ],
    )
    child = WorkItem(
        project_id=project.id,
        title="child",
        external_refs=[
            ExternalReference(
                provider="openproject", external_id="43", external_type="work_package"
            )
        ],
    )
    await projects.create(project)
    await work_items.create(parent)
    await work_items.create(child)
    await comments.create(
        Comment(
            work_item_id=child.id,
            text="note",
            external_refs=[
                ExternalReference(provider="openproject", external_id="9", external_type="activity")
            ],
        )
    )
    await attachments.create(
        Attachment(
            work_item_id=child.id,
            file_name="a.pdf",
            external_refs=[
                ExternalReference(
                    provider="openproject", external_id="3", external_type="attachment"
                )
            ],
        )
    )
    await relations.create(
        WorkItemRelation(
            source_work_item_id=parent.id,
            target_work_item_id=child.id,
            relation_type=WorkItemRelationType.PARENT_OF,
        )
    )

    found_project = await projects.find_by_external_ref("openproject", "8")
    assert found_project is not None
    assert found_project.id == project.id
    found_child = await work_items.find_by_external_ref("openproject", "43")
    assert found_child is not None
    assert found_child.id == child.id
    assert await work_items.find_by_external_ref("openproject", "nope") is None
    found_comment = await comments.find_by_external_ref("openproject", "9")
    assert found_comment is not None
    assert found_comment.work_item_id == child.id
    found_attachment = await attachments.find_by_external_ref("openproject", "3")
    assert found_attachment is not None
    assert found_attachment.file_name == "a.pdf"
    assert len(await relations.list_by_work_item(child.id)) == 1


# --- Type/status mapping (0.8) ----------------------------------------------


def test_gate_openproject_type_mapping() -> None:
    assert map_work_item_type("Task") == WorkItemType.TASK
    assert map_work_item_type("bug") == WorkItemType.BUG
    assert map_work_item_type("User story") == WorkItemType.STORY
    assert map_work_item_type("Milestone") == WorkItemType.TASK
    assert map_work_item_type("Unknown Type") == WorkItemType.TASK
    assert map_work_item_type("") == WorkItemType.TASK
    assert map_work_item_type_or_none("Task") == WorkItemType.TASK
    assert map_work_item_type_or_none("Unknown Type") is None


def test_gate_openproject_status_mapping() -> None:
    assert map_human_work_status("In progress") == HumanWorkStatus.IN_PROGRESS
    assert map_human_work_status("Closed") == HumanWorkStatus.DONE
    assert map_human_work_status("Rejected") == HumanWorkStatus.CANCELLED
    assert map_human_work_status("Done") == HumanWorkStatus.DONE
    assert map_human_work_status("Blocked") == HumanWorkStatus.BLOCKED
    assert map_human_work_status("Mystery") == HumanWorkStatus.NEW
    assert map_human_work_status_or_none("In progress") == HumanWorkStatus.IN_PROGRESS
    assert map_human_work_status_or_none("Mystery") is None
