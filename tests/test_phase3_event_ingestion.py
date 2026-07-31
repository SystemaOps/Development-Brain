from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert

from agent_core.application.event_classification import normalize_openproject_event
from agent_core.application.retry_policy import (
    calculate_retry_delay_seconds,
    classify_exception,
)
from agent_core.adapters.redis_queue import RedisEventQueue
from agent_core.domain.enums import AgentExecutionStatus, RetryCategory
from agent_core.domain.events import EventEnvelope, calculate_event_idempotency_key
from agent_core.models import AgentExecution, AgentJob, OpenProjectContextSnapshot, WebhookEvent


def test_event_idempotency_key_is_stable_for_payload_key_order_and_ignores_headers():
    first = EventEnvelope(
        source="openproject",
        event_type="work_package.updated",
        external_project_id="12",
        external_work_package_id="34",
        payload={"b": 2, "a": {"nested": True}},
        headers={"x-request-id": "one"},
    )
    second = EventEnvelope(
        source="openproject",
        event_type="work_package.updated",
        external_project_id="12",
        external_work_package_id="34",
        payload={"a": {"nested": True}, "b": 2},
        headers={"x-request-id": "two"},
    )

    assert first.idempotency_key == second.idempotency_key
    assert first.idempotency_key.startswith("openproject:")


def test_event_idempotency_key_changes_when_payload_changes():
    original = calculate_event_idempotency_key(
        source="openproject",
        event_type="work_package.updated",
        external_project_id="12",
        external_work_package_id="34",
        external_comment_id=None,
        payload={"subject": "First"},
    )
    changed = calculate_event_idempotency_key(
        source="openproject",
        event_type="work_package.updated",
        external_project_id="12",
        external_work_package_id="34",
        external_comment_id=None,
        payload={"subject": "Second"},
    )

    assert original != changed


def test_normalize_openproject_event_extracts_ids_and_event_type_from_links():
    envelope = normalize_openproject_event(
        payload={
            "action": "work_package.updated",
            "_links": {
                "workPackage": {"href": "/api/v3/work_packages/34"},
                "project": {"href": "/api/v3/projects/12"},
            },
            "activity": {"_type": "Activity::Comment", "id": 56},
        },
        headers={"X-Request-ID": "abc"},
    )

    assert envelope.source == "openproject"
    assert envelope.event_type == "work_package.updated"
    assert envelope.external_project_id == "12"
    assert envelope.external_work_package_id == "34"
    assert envelope.external_comment_id == "56"
    assert envelope.headers == {"x-request-id": "abc"}
    assert envelope.idempotency_key


def test_webhook_orm_models_cover_existing_tables_and_idempotency_column():
    assert WebhookEvent.__tablename__ == "pm_webhook_events"
    assert AgentJob.__tablename__ == "agent_jobs"
    assert OpenProjectContextSnapshot.__tablename__ == "pm_context_snapshots"

    assert "idempotency_key" in WebhookEvent.__table__.columns
    assert WebhookEvent.__table__.columns["idempotency_key"].unique
    assert not WebhookEvent.__table__.columns["idempotency_key"].nullable
    assert "retry_at" in WebhookEvent.__table__.columns
    assert "attempt_count" in AgentJob.__table__.columns
    assert "retry_at" in AgentJob.__table__.columns
    assert "lease_owner" in AgentJob.__table__.columns
    assert "lease_expires_at" in AgentJob.__table__.columns
    assert "last_error" in AgentJob.__table__.columns


def test_agent_execution_model_matches_readme_execution_tracking_shape():
    assert AgentExecution.__tablename__ == "agent_executions"
    assert AgentExecutionStatus.RUNNING.value == "running"

    columns = AgentExecution.__table__.columns
    assert "project_id" in columns
    assert "agent_name" in columns
    assert "thread_id" in columns
    assert "trigger_event_id" in columns
    assert "parent_execution_id" in columns
    assert "attempt_number" in columns
    assert "status" in columns
    assert "config_snapshot" in columns
    assert "started_at" in columns
    assert "ended_at" in columns
    assert "error_summary" in columns

    index_names = {index.name for index in AgentExecution.__table__.indexes}
    assert "idx_agent_executions_thread_started" in index_names
    assert "idx_agent_executions_project_status" in index_names
    assert "idx_agent_executions_trigger_event" in index_names


def test_webhook_event_insert_supports_postgres_conflict_handling():
    statement = (
        insert(WebhookEvent)
        .values(
            source_tool="openproject",
            event_type="work_package.updated",
            idempotency_key="openproject:test",
            headers={},
            payload={},
        )
        .on_conflict_do_nothing(index_elements=[WebhookEvent.idempotency_key])
    )

    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (idempotency_key) DO NOTHING" in compiled


class FakeRedisClient:
    def __init__(self):
        self.items: list[tuple[str, str]] = []

    async def lpush(self, queue_name: str, event_id: str) -> None:
        self.items.insert(0, (queue_name, event_id))

    async def brpop(self, queue_name: str, timeout: int):
        if not self.items:
            return None
        queued_name, event_id = self.items.pop()
        assert queued_name == queue_name
        return queued_name, event_id


@pytest.mark.asyncio
async def test_redis_event_queue_uses_configured_queue_name():
    client = FakeRedisClient()
    queue = RedisEventQueue(client=client, queue_name="events")

    await queue.enqueue("event-1")

    assert await queue.dequeue(timeout_seconds=1) == "event-1"
    assert await queue.dequeue(timeout_seconds=1) is None


def test_retry_policy_classifies_retryable_and_terminal_errors():
    assert classify_exception(TimeoutError("timed out")).category == RetryCategory.TRANSIENT_NETWORK
    assert classify_exception(TimeoutError("timed out")).retryable

    assert classify_exception(ConnectionError("connection refused")).category == (
        RetryCategory.DEPENDENCY_UNAVAILABLE
    )
    assert classify_exception(RuntimeError("HTTP 503 service unavailable")).category == (
        RetryCategory.DEPENDENCY_UNAVAILABLE
    )
    assert classify_exception(RuntimeError("HTTP 503 service unavailable")).retryable
    assert classify_exception(RuntimeError("HTTP 409 conflict")).category == (
        RetryCategory.OPTIMISTIC_CONCURRENCY_CONFLICT
    )
    assert classify_exception(RuntimeError("HTTP 401 unauthorized")).category == (
        RetryCategory.AUTHENTICATION_FAILURE
    )
    assert not classify_exception(ValueError("bad payload")).retryable


def test_retry_delay_uses_bounded_exponential_backoff():
    assert calculate_retry_delay_seconds(
        1,
        base_seconds=30,
        max_seconds=600,
    ) == 30
    assert calculate_retry_delay_seconds(
        3,
        base_seconds=30,
        max_seconds=600,
    ) == 120
    assert calculate_retry_delay_seconds(
        99,
        base_seconds=30,
        max_seconds=600,
    ) == 600
