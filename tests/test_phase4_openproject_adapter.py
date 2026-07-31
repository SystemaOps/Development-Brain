from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from agent_core.adapters.openproject import (
    OpenProjectClient,
    has_openproject_idempotency_marker,
    markdown_with_idempotency_marker,
    resolve_openproject_api_token,
)
from agent_core.application.openproject_feedback import (
    OpenProjectFeedbackIntent,
    classify_openproject_feedback,
)
from agent_core.application.project_orchestrator import should_resume_planning
from agent_core.domain.events import EventEnvelope
from agent_core.models import (
    ExternalArtifact,
    OpenProjectOutboundOperation,
    OpenProjectReconciliationSnapshot,
)
from agent_core.persistence.openproject_artifacts import (
    SqlAlchemyOpenProjectArtifactStore,
)
from agent_core.persistence.openproject_outbox import (
    SqlAlchemyOpenProjectOutboundStore,
)
from agent_core.persistence.openproject_reconciliation import (
    SqlAlchemyOpenProjectReconciliationStore,
)
from agent_core.ports.openproject import (
    OpenProjectArtifactMapping,
    OpenProjectOperationClaim,
    OpenProjectOperationStatus,
    OpenProjectOperationType,
)


def test_openproject_outbound_operation_model_tracks_idempotent_mutations():
    assert OpenProjectOutboundOperation.__tablename__ == "openproject_outbound_operations"

    columns = OpenProjectOutboundOperation.__table__.columns
    assert "idempotency_key" in columns
    assert "operation_type" in columns
    assert "status" in columns
    assert "request_payload" in columns
    assert "response_payload" in columns
    assert "target_artifact_type" in columns
    assert "target_external_id" in columns

    constraints = {
        constraint.name for constraint in OpenProjectOutboundOperation.__table__.constraints
    }
    assert "uq_openproject_outbound_operations_idempotency_key" in constraints
    assert "ck_openproject_outbound_operations_type" in constraints
    assert "ck_openproject_outbound_operations_status" in constraints


def test_openproject_reconciliation_snapshot_model_preserves_pre_update_state():
    assert (
        OpenProjectReconciliationSnapshot.__tablename__
        == "openproject_reconciliation_snapshots"
    )

    columns = OpenProjectReconciliationSnapshot.__table__.columns
    assert "outbound_idempotency_key" in columns
    assert "operation_type" in columns
    assert "target_artifact_type" in columns
    assert "target_external_id" in columns
    assert "before_payload" in columns
    assert "before_activities_payload" in columns
    assert "agent_payload" in columns
    assert "detected_human_edits" in columns


def test_external_artifact_model_tracks_openproject_projection_mappings():
    assert ExternalArtifact.__tablename__ == "external_artifacts"

    columns = ExternalArtifact.__table__.columns
    assert "project_id" in columns
    assert "node_identity_id" in columns
    assert "system_name" in columns
    assert "artifact_type" in columns
    assert "external_id" in columns
    assert "external_url" in columns
    assert "external_payload" in columns

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in ExternalArtifact.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("system_name", "artifact_type", "external_id") in unique_columns


class FakeSession:
    def __init__(self, scalar_results: list[Any]):
        self.scalar_results = scalar_results
        self.statements: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.scalar_results.pop(0)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class FakeAddSession:
    def __init__(self):
        self.added: list[Any] = []
        self.commits = 0

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_openproject_outbound_store_claims_new_operation_with_conflict_sql():
    session = FakeSession([uuid4()])
    store = SqlAlchemyOpenProjectOutboundStore(session)

    claim = await store.claim_operation(
        idempotency_key="op:comment:1",
        operation_type=OpenProjectOperationType.ADD_COMMENT,
        request_payload={"markdown": "hello"},
        target_artifact_type="work_package",
        target_external_id="34",
    )

    compiled = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (idempotency_key) DO NOTHING" in compiled
    assert claim.should_execute is True
    assert claim.status == OpenProjectOperationStatus.PENDING
    assert claim.reclaimed is False
    assert session.commits == 1


@pytest.mark.asyncio
async def test_openproject_artifact_store_upserts_mapping_with_conflict_update():
    artifact_id = uuid4()
    local_project_id = uuid4()
    node_identity_id = uuid4()
    session = FakeSession([artifact_id])
    store = SqlAlchemyOpenProjectArtifactStore(session)

    mapping = await store.upsert_mapping(
        project_id=local_project_id,
        node_identity_id=node_identity_id,
        artifact_type="work_package",
        external_id="34",
        external_url="/api/v3/work_packages/34",
        external_payload={"id": 34, "subject": "Build thing"},
    )

    compiled = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (system_name, artifact_type, external_id) DO UPDATE" in compiled
    assert mapping == OpenProjectArtifactMapping(
        artifact_id=artifact_id,
        project_id=local_project_id,
        node_identity_id=node_identity_id,
        artifact_type="work_package",
        external_id="34",
        external_url="/api/v3/work_packages/34",
        external_payload={"id": 34, "subject": "Build thing"},
    )
    assert session.commits == 1


@pytest.mark.asyncio
async def test_openproject_outbound_store_returns_existing_operation_without_execute():
    existing = SimpleNamespace(
        operation_type=OpenProjectOperationType.ADD_COMMENT.value,
        status=OpenProjectOperationStatus.SUCCEEDED.value,
        response_payload={"id": "activity-1"},
        error_message=None,
    )
    session = FakeSession([None, existing])
    store = SqlAlchemyOpenProjectOutboundStore(session)

    claim = await store.claim_operation(
        idempotency_key="op:comment:1",
        operation_type=OpenProjectOperationType.ADD_COMMENT,
        request_payload={"markdown": "hello"},
    )

    assert claim.should_execute is False
    assert claim.status == OpenProjectOperationStatus.SUCCEEDED
    assert claim.response_payload == {"id": "activity-1"}
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_openproject_outbound_store_reclaims_failed_operation_for_retry():
    existing = SimpleNamespace(
        operation_type=OpenProjectOperationType.ADD_COMMENT.value,
        status=OpenProjectOperationStatus.FAILED.value,
        project_id=None,
        artifact_id=None,
        target_artifact_type="work_package",
        target_external_id="34",
        request_payload={"markdown": "old"},
        response_payload=None,
        error_message="temporary failure",
        completed_at=object(),
    )
    local_project_id = uuid4()
    session = FakeSession([None, existing])
    store = SqlAlchemyOpenProjectOutboundStore(session)

    claim = await store.claim_operation(
        idempotency_key="op:comment:retry",
        operation_type=OpenProjectOperationType.ADD_COMMENT,
        request_payload={"markdown": "new"},
        project_id=local_project_id,
        target_artifact_type="work_package",
        target_external_id="34",
    )

    assert claim.should_execute is True
    assert claim.status == OpenProjectOperationStatus.PENDING
    assert claim.reclaimed is True
    assert existing.status == OpenProjectOperationStatus.PENDING.value
    assert existing.project_id == local_project_id
    assert existing.request_payload == {"markdown": "new"}
    assert existing.error_message is None
    assert existing.completed_at is None
    assert session.commits == 1


@pytest.mark.asyncio
async def test_openproject_outbound_store_marks_success_and_failure():
    succeeded = SimpleNamespace(
        status=OpenProjectOperationStatus.PENDING.value,
        response_payload=None,
        error_message="old",
        completed_at=None,
    )
    success_session = FakeSession([succeeded])
    await SqlAlchemyOpenProjectOutboundStore(success_session).mark_succeeded(
        idempotency_key="op:comment:1",
        response_payload={"id": "activity-1"},
    )

    assert succeeded.status == OpenProjectOperationStatus.SUCCEEDED.value
    assert succeeded.response_payload == {"id": "activity-1"}
    assert succeeded.error_message is None
    assert succeeded.completed_at is not None
    assert success_session.commits == 1

    failed = SimpleNamespace(
        status=OpenProjectOperationStatus.PENDING.value,
        response_payload=None,
        error_message=None,
        completed_at=None,
    )
    failure_session = FakeSession([failed])
    await SqlAlchemyOpenProjectOutboundStore(failure_session).mark_failed(
        idempotency_key="op:comment:1",
        error_message="bad request",
    )

    assert failed.status == OpenProjectOperationStatus.FAILED.value
    assert failed.error_message == "bad request"
    assert failed.completed_at is not None
    assert failure_session.commits == 1


@pytest.mark.asyncio
async def test_openproject_reconciliation_store_records_snapshot():
    session = FakeAddSession()
    await SqlAlchemyOpenProjectReconciliationStore(session).record_snapshot(
        outbound_idempotency_key="op:wp:1",
        operation_type=OpenProjectOperationType.CREATE_OR_UPDATE_WORK_PACKAGE,
        target_artifact_type="work_package",
        target_external_id="34",
        before_payload={"subject": "Human edit"},
        before_activities_payload={"_embedded": {"elements": []}},
        agent_payload={"subject": "Agent edit"},
        detected_human_edits=[
            {
                "field": "subject",
                "before": "Human edit",
                "agent": "Agent edit",
            }
        ],
    )

    snapshot = session.added[0]
    assert snapshot.outbound_idempotency_key == "op:wp:1"
    assert snapshot.operation_type == (
        OpenProjectOperationType.CREATE_OR_UPDATE_WORK_PACKAGE.value
    )
    assert snapshot.before_payload == {"subject": "Human edit"}
    assert snapshot.before_activities_payload == {"_embedded": {"elements": []}}
    assert snapshot.agent_payload == {"subject": "Agent edit"}
    assert snapshot.detected_human_edits == [
        {
            "field": "subject",
            "before": "Human edit",
            "agent": "Agent edit",
        }
    ]
    assert session.commits == 1


def test_openproject_adapter_loads_token_file_and_marks_comments(tmp_path):
    token_file = tmp_path / "openproject_api_token"
    token_file.write_text("file-token\n", encoding="utf-8")

    assert resolve_openproject_api_token(
        api_key="placeholder-key",
        api_token_file=str(token_file),
    ) == "file-token"

    marked = markdown_with_idempotency_marker("Agent update", "op:comment:1")

    assert "Agent update" in marked
    assert has_openproject_idempotency_marker(marked)
    assert has_openproject_idempotency_marker(marked, "op:comment:1")


@pytest.mark.asyncio
async def test_openproject_adapter_loads_resource_catalog_from_hal_collections():
    http_client = FakeHttpClient(
        [
            FakeResponse(
                {
                    "_embedded": {
                        "elements": [
                            {
                                "name": "Task",
                                "_links": {"self": {"href": "/api/v3/types/3"}},
                            }
                        ]
                    }
                }
            ),
            FakeResponse(
                {
                    "_embedded": {
                        "elements": [
                            {
                                "name": "In progress",
                                "_links": {"self": {"href": "/api/v3/statuses/5"}},
                            }
                        ]
                    }
                }
            ),
            FakeResponse(
                {
                    "_embedded": {
                        "elements": [
                            {
                                "name": "Normal",
                                "_links": {"self": {"href": "/api/v3/priorities/2"}},
                            }
                        ]
                    }
                }
            ),
        ]
    )
    client = OpenProjectClient(http_client=http_client)

    catalog = await client.load_resource_catalog()

    assert catalog.type_hrefs == {"Task": "/api/v3/types/3"}
    assert catalog.status_hrefs == {"In progress": "/api/v3/statuses/5"}
    assert catalog.priority_hrefs == {"Normal": "/api/v3/priorities/2"}
    assert [request["path"] for request in http_client.requests] == [
        "/types",
        "/statuses",
        "/priorities",
    ]


def test_openproject_feedback_classifier_ignores_agent_echo_comments():
    envelope = EventEnvelope(
        source="openproject",
        event_type="work_package.comment_created",
        external_comment_id="99",
        payload={
            "comment": {
                "raw": markdown_with_idempotency_marker(
                    "Agent update",
                    "op:comment:1",
                )
            }
        },
    )

    classification = classify_openproject_feedback(envelope)

    assert classification.intent == OpenProjectFeedbackIntent.AGENT_ECHO
    assert classification.self_generated is True
    assert classification.resumable is False
    assert should_resume_planning(envelope) is False


def test_openproject_feedback_classifier_routes_human_feedback_intents():
    assert classify_openproject_feedback(
        EventEnvelope(
            source="openproject",
            event_type="work_package.comment_created",
            external_comment_id="100",
            payload={"comment": {"raw": "Please approve this plan."}},
        )
    ).intent == OpenProjectFeedbackIntent.APPROVAL

    assert classify_openproject_feedback(
        EventEnvelope(
            source="openproject",
            event_type="work_package.comment_created",
            external_comment_id="101",
            payload={"comment": {"raw": "Requirement change: add audit logs."}},
        )
    ).intent == OpenProjectFeedbackIntent.REQUIREMENT_CHANGE

    assert classify_openproject_feedback(
        EventEnvelope(
            source="openproject",
            event_type="work_package.updated",
            payload={"action": "work_package.updated"},
        )
    ).resumable is False


class FakeOutboundStore:
    def __init__(self, claim: OpenProjectOperationClaim):
        self.claim = claim
        self.claim_calls: list[dict[str, Any]] = []
        self.succeeded_calls: list[dict[str, Any]] = []
        self.failed_calls: list[dict[str, Any]] = []

    async def claim_operation(self, **kwargs):
        self.claim_calls.append(kwargs)
        return self.claim

    async def mark_succeeded(self, **kwargs):
        self.succeeded_calls.append(kwargs)

    async def mark_failed(self, **kwargs):
        self.failed_calls.append(kwargs)


class FakeReconciliationStore:
    def __init__(self):
        self.snapshot_calls: list[dict[str, Any]] = []

    async def record_snapshot(self, **kwargs):
        self.snapshot_calls.append(kwargs)


class FakeArtifactStore:
    def __init__(self):
        self.mapping_calls: list[dict[str, Any]] = []

    async def upsert_mapping(self, **kwargs):
        artifact_id = uuid4()
        self.mapping_calls.append({"artifact_id": artifact_id, **kwargs})
        return OpenProjectArtifactMapping(
            artifact_id=artifact_id,
            project_id=kwargs["project_id"],
            node_identity_id=kwargs.get("node_identity_id"),
            artifact_type=kwargs["artifact_type"],
            external_id=kwargs["external_id"],
            external_url=kwargs.get("external_url"),
            external_payload=kwargs.get("external_payload"),
        )


class FakeResponse:
    def __init__(self, payload: dict[str, Any], error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.content = b"{}"

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = responses
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    async def request(self, method: str, path: str, **kwargs):
        self.requests.append({"method": method, "path": path, **kwargs})
        return self.responses.pop(0)

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_openproject_adapter_add_comment_uses_idempotency_store_and_marker():
    store = FakeOutboundStore(
        OpenProjectOperationClaim(
            idempotency_key="op:comment:1",
            operation_type=OpenProjectOperationType.ADD_COMMENT,
            status=OpenProjectOperationStatus.PENDING,
            should_execute=True,
        )
    )
    http_client = FakeHttpClient(
        [
            FakeResponse(
                {
                    "_links": {
                        "addComment": {
                            "href": "/api/v3/work_packages/34/activities",
                        }
                    }
                }
            ),
            FakeResponse({"id": "activity-1"}),
        ]
    )
    client = OpenProjectClient(outbound_store=store, http_client=http_client)

    result = await client.add_comment(
        work_package_id="34",
        external_idempotency_key="op:comment:1",
        markdown="Agent update",
    )

    assert result == {"id": "activity-1"}
    assert store.claim_calls[0]["operation_type"] == OpenProjectOperationType.ADD_COMMENT
    assert store.claim_calls[0]["target_external_id"] == "34"
    assert http_client.requests[0]["method"] == "GET"
    assert http_client.requests[0]["path"] == "/work_packages/34"
    assert http_client.requests[1]["method"] == "POST"
    assert http_client.requests[1]["path"] == "/work_packages/34/activities"
    comment_raw = http_client.requests[1]["json"]["comment"]["raw"]
    assert "Agent update" in comment_raw
    assert has_openproject_idempotency_marker(comment_raw, "op:comment:1")
    assert store.succeeded_calls == [
        {
            "idempotency_key": "op:comment:1",
            "response_payload": {"id": "activity-1"},
        }
    ]


@pytest.mark.asyncio
async def test_openproject_adapter_skips_duplicate_completed_comment():
    store = FakeOutboundStore(
        OpenProjectOperationClaim(
            idempotency_key="op:comment:1",
            operation_type=OpenProjectOperationType.ADD_COMMENT,
            status=OpenProjectOperationStatus.SUCCEEDED,
            should_execute=False,
            response_payload={"id": "activity-1"},
        )
    )
    http_client = FakeHttpClient([])
    client = OpenProjectClient(outbound_store=store, http_client=http_client)

    result = await client.add_comment(
        work_package_id="34",
        external_idempotency_key="op:comment:1",
        markdown="Agent update",
    )

    assert result == {"id": "activity-1"}
    assert http_client.requests == []
    assert store.succeeded_calls == []


@pytest.mark.asyncio
async def test_openproject_adapter_reconciles_reclaimed_comment_before_retrying():
    idempotency_key = "op:comment:retry"
    store = FakeOutboundStore(
        OpenProjectOperationClaim(
            idempotency_key=idempotency_key,
            operation_type=OpenProjectOperationType.ADD_COMMENT,
            status=OpenProjectOperationStatus.PENDING,
            should_execute=True,
            reclaimed=True,
        )
    )
    existing_activity = {
        "id": "activity-1",
        "comment": {
            "raw": markdown_with_idempotency_marker(
                "Agent update",
                idempotency_key,
            )
        },
    }
    http_client = FakeHttpClient(
        [
            FakeResponse({"id": 34}),
            FakeResponse({"_embedded": {"elements": [existing_activity]}}),
        ]
    )
    client = OpenProjectClient(outbound_store=store, http_client=http_client)

    result = await client.add_comment(
        work_package_id="34",
        external_idempotency_key=idempotency_key,
        markdown="Agent update",
    )

    assert result == existing_activity
    assert [request["path"] for request in http_client.requests] == [
        "/work_packages/34",
        "/work_packages/34/activities",
    ]
    assert store.succeeded_calls == [
        {
            "idempotency_key": idempotency_key,
            "response_payload": existing_activity,
        }
    ]


@pytest.mark.asyncio
async def test_openproject_adapter_create_work_package_is_claimed_before_post():
    store = FakeOutboundStore(
        OpenProjectOperationClaim(
            idempotency_key="op:wp:1",
            operation_type=OpenProjectOperationType.CREATE_OR_UPDATE_WORK_PACKAGE,
            status=OpenProjectOperationStatus.PENDING,
            should_execute=True,
        )
    )
    http_client = FakeHttpClient([FakeResponse({"id": 77})])
    client = OpenProjectClient(outbound_store=store, http_client=http_client)

    result = await client.create_or_update_work_package(
        project_id="12",
        external_idempotency_key="op:wp:1",
        payload={"subject": "Build thing"},
    )

    assert result == {"id": 77}
    assert store.claim_calls[0]["operation_type"] == (
        OpenProjectOperationType.CREATE_OR_UPDATE_WORK_PACKAGE
    )
    assert store.claim_calls[0]["request_payload"] == {
        "project_id": "12",
        "payload": {"subject": "Build thing"},
    }
    assert http_client.requests == [
        {
            "method": "POST",
            "path": "/projects/12/work_packages",
            "json": {"subject": "Build thing"},
        }
    ]
    assert store.succeeded_calls[0]["response_payload"] == {"id": 77}


@pytest.mark.asyncio
async def test_openproject_adapter_upserts_project_mapping_after_create_project():
    local_project_id = uuid4()
    artifact_store = FakeArtifactStore()
    response_payload = {
        "id": 12,
        "identifier": "ada-core",
        "_links": {"self": {"href": "/api/v3/projects/12"}},
    }
    http_client = FakeHttpClient([FakeResponse(response_payload)])
    client = OpenProjectClient(
        artifact_store=artifact_store,
        http_client=http_client,
    )

    result = await client.create_project(
        "ada-core",
        "Ada Core",
        "Planning project",
        local_project_id=local_project_id,
    )

    assert result == response_payload
    assert artifact_store.mapping_calls == [
        {
            "artifact_id": artifact_store.mapping_calls[0]["artifact_id"],
            "project_id": local_project_id,
            "node_identity_id": None,
            "artifact_type": "project",
            "external_id": "12",
            "external_url": "/api/v3/projects/12",
            "external_payload": response_payload,
        }
    ]


@pytest.mark.asyncio
async def test_openproject_adapter_upserts_mapping_after_work_package_create():
    local_project_id = uuid4()
    node_identity_id = uuid4()
    store = FakeOutboundStore(
        OpenProjectOperationClaim(
            idempotency_key="op:wp:1",
            operation_type=OpenProjectOperationType.CREATE_OR_UPDATE_WORK_PACKAGE,
            status=OpenProjectOperationStatus.PENDING,
            should_execute=True,
        )
    )
    artifact_store = FakeArtifactStore()
    response_payload = {
        "id": 77,
        "subject": "Build thing",
        "_links": {"self": {"href": "/api/v3/work_packages/77"}},
    }
    http_client = FakeHttpClient([FakeResponse(response_payload)])
    client = OpenProjectClient(
        artifact_store=artifact_store,
        outbound_store=store,
        http_client=http_client,
    )

    result = await client.create_or_update_work_package(
        project_id="12",
        external_idempotency_key="op:wp:1",
        payload={"subject": "Build thing"},
        local_project_id=local_project_id,
        node_identity_id=node_identity_id,
    )

    assert result == response_payload
    assert store.claim_calls[0]["project_id"] == local_project_id
    assert artifact_store.mapping_calls[0] == {
        "artifact_id": artifact_store.mapping_calls[0]["artifact_id"],
        "project_id": local_project_id,
        "node_identity_id": node_identity_id,
        "artifact_type": "work_package",
        "external_id": "77",
        "external_url": "/api/v3/work_packages/77",
        "external_payload": response_payload,
    }


@pytest.mark.asyncio
async def test_openproject_adapter_refreshes_mapping_for_duplicate_success_response():
    local_project_id = uuid4()
    response_payload = {
        "id": 77,
        "subject": "Build thing",
        "_links": {"self": {"href": "/api/v3/work_packages/77"}},
    }
    store = FakeOutboundStore(
        OpenProjectOperationClaim(
            idempotency_key="op:wp:1",
            operation_type=OpenProjectOperationType.CREATE_OR_UPDATE_WORK_PACKAGE,
            status=OpenProjectOperationStatus.SUCCEEDED,
            should_execute=False,
            response_payload=response_payload,
        )
    )
    artifact_store = FakeArtifactStore()
    http_client = FakeHttpClient([])
    client = OpenProjectClient(
        artifact_store=artifact_store,
        outbound_store=store,
        http_client=http_client,
    )

    result = await client.create_or_update_work_package(
        project_id="12",
        external_idempotency_key="op:wp:1",
        payload={"subject": "Build thing"},
        local_project_id=local_project_id,
    )

    assert result == response_payload
    assert http_client.requests == []
    assert artifact_store.mapping_calls[0]["project_id"] == local_project_id
    assert artifact_store.mapping_calls[0]["external_id"] == "77"


@pytest.mark.asyncio
async def test_openproject_adapter_records_reconciliation_snapshot_before_update():
    local_project_id = uuid4()
    node_identity_id = uuid4()
    store = FakeOutboundStore(
        OpenProjectOperationClaim(
            idempotency_key="op:wp:34",
            operation_type=OpenProjectOperationType.CREATE_OR_UPDATE_WORK_PACKAGE,
            status=OpenProjectOperationStatus.PENDING,
            should_execute=True,
        )
    )
    artifact_store = FakeArtifactStore()
    reconciliation_store = FakeReconciliationStore()
    before_payload = {
        "id": 34,
        "lockVersion": 7,
        "subject": "Human subject",
        "description": {"raw": "Human description"},
        "_links": {
            "self": {"href": "/api/v3/work_packages/34"},
            "status": {"title": "Ready"},
            "type": {"title": "Task"},
        },
    }
    activities_payload = {"_embedded": {"elements": [{"id": 1}]}}
    agent_payload = {
        "id": "34",
        "subject": "Agent subject",
        "description": {"raw": "Agent description"},
        "_links": {
            "status": {"title": "In progress"},
            "type": {"title": "Task"},
        },
    }
    response_payload = {
        "id": 34,
        "subject": "Agent subject",
        "_links": {"self": {"href": "/api/v3/work_packages/34"}},
    }
    http_client = FakeHttpClient(
        [
            FakeResponse(before_payload),
            FakeResponse(activities_payload),
            FakeResponse(response_payload),
        ]
    )
    client = OpenProjectClient(
        artifact_store=artifact_store,
        outbound_store=store,
        reconciliation_store=reconciliation_store,
        http_client=http_client,
    )

    result = await client.create_or_update_work_package(
        project_id="12",
        external_idempotency_key="op:wp:34",
        payload=agent_payload,
        local_project_id=local_project_id,
        node_identity_id=node_identity_id,
    )

    assert result == response_payload
    assert [request["method"] for request in http_client.requests] == [
        "GET",
        "GET",
        "PATCH",
    ]
    assert [request["path"] for request in http_client.requests] == [
        "/work_packages/34",
        "/work_packages/34/activities",
        "/work_packages/34",
    ]
    assert http_client.requests[2]["json"] == {
        **agent_payload,
        "lockVersion": 7,
    }
    assert artifact_store.mapping_calls[0]["project_id"] == local_project_id
    assert artifact_store.mapping_calls[0]["node_identity_id"] == node_identity_id
    assert artifact_store.mapping_calls[0]["external_payload"] == before_payload
    assert artifact_store.mapping_calls[1]["external_payload"] == response_payload
    assert reconciliation_store.snapshot_calls[0]["project_id"] == local_project_id
    assert reconciliation_store.snapshot_calls[0]["artifact_id"] == (
        artifact_store.mapping_calls[0]["artifact_id"]
    )
    assert reconciliation_store.snapshot_calls[0]["before_payload"] == before_payload
    assert reconciliation_store.snapshot_calls[0]["before_activities_payload"] == (
        activities_payload
    )
    assert reconciliation_store.snapshot_calls[0]["agent_payload"] == agent_payload
    assert reconciliation_store.snapshot_calls[0]["detected_human_edits"] == [
        {
            "field": "subject",
            "before": "Human subject",
            "agent": "Agent subject",
        },
        {
            "field": "description.raw",
            "before": "Human description",
            "agent": "Agent description",
        },
        {
            "field": "status",
            "before": "Ready",
            "agent": "In progress",
        },
    ]


@pytest.mark.asyncio
async def test_openproject_adapter_records_reconciliation_snapshot_before_comment():
    local_project_id = uuid4()
    node_identity_id = uuid4()
    store = FakeOutboundStore(
        OpenProjectOperationClaim(
            idempotency_key="op:comment:34",
            operation_type=OpenProjectOperationType.ADD_COMMENT,
            status=OpenProjectOperationStatus.PENDING,
            should_execute=True,
        )
    )
    artifact_store = FakeArtifactStore()
    reconciliation_store = FakeReconciliationStore()
    before_payload = {
        "_links": {
            "self": {
                "href": "/api/v3/work_packages/34",
            },
            "addComment": {
                "href": "/api/v3/work_packages/34/activities",
            }
        }
    }
    http_client = FakeHttpClient(
        [
            FakeResponse(before_payload),
            FakeResponse({"id": "activity-1"}),
        ]
    )
    client = OpenProjectClient(
        artifact_store=artifact_store,
        outbound_store=store,
        reconciliation_store=reconciliation_store,
        http_client=http_client,
    )

    await client.add_comment(
        work_package_id="34",
        external_idempotency_key="op:comment:34",
        markdown="Agent update",
        local_project_id=local_project_id,
        node_identity_id=node_identity_id,
    )

    assert store.claim_calls[0]["project_id"] == local_project_id
    assert artifact_store.mapping_calls[0]["project_id"] == local_project_id
    assert artifact_store.mapping_calls[0]["node_identity_id"] == node_identity_id
    assert artifact_store.mapping_calls[0]["external_id"] == "34"
    assert reconciliation_store.snapshot_calls[0]["operation_type"] == (
        OpenProjectOperationType.ADD_COMMENT
    )
    assert reconciliation_store.snapshot_calls[0]["target_external_id"] == "34"
    assert reconciliation_store.snapshot_calls[0]["before_payload"] == before_payload
    assert reconciliation_store.snapshot_calls[0]["project_id"] == local_project_id
    assert reconciliation_store.snapshot_calls[0]["artifact_id"] == (
        artifact_store.mapping_calls[0]["artifact_id"]
    )
    assert has_openproject_idempotency_marker(
        reconciliation_store.snapshot_calls[0]["agent_payload"]["comment"]["raw"],
        "op:comment:34",
    )
