from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agent_core.application.event_classification import normalize_openproject_event
from agent_core.domain.enums import RetryCategory


def _import_trigger_module(monkeypatch, module_name: str):
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(repo_root / "infra" / "agent_trigger"))
    return importlib.import_module(module_name)


def test_trigger_event_parser_idempotency_matches_core(monkeypatch):
    trigger_parser = _import_trigger_module(monkeypatch, "app.event_parser")

    payload = {
        "action": "work_package.updated",
        "_links": {
            "workPackage": {"href": "/api/v3/work_packages/34"},
            "project": {"href": "/api/v3/projects/12"},
        },
    }
    headers = {"x-request-id": "ignored"}

    trigger_event = trigger_parser.normalize_openproject_event(payload, headers)
    core_event = normalize_openproject_event(payload, headers)

    assert trigger_event["source_tool"] == core_event.source
    assert trigger_event["event_type"] == core_event.event_type
    assert trigger_event["external_project_id"] == core_event.external_project_id
    assert trigger_event["external_work_package_id"] == core_event.external_work_package_id
    assert trigger_event["idempotency_key"] == core_event.idempotency_key
    assert trigger_parser.find_work_package_id.__module__.startswith("agent_core.")


def test_trigger_retry_policy_reexports_core_policy(monkeypatch):
    trigger_retry_policy = _import_trigger_module(monkeypatch, "app.retry_policy")

    decision = trigger_retry_policy.classify_exception(TimeoutError("timed out"))

    assert decision.category == RetryCategory.TRANSIENT_NETWORK
    assert trigger_retry_policy.calculate_retry_delay_seconds(
        2,
        base_seconds=3,
        max_seconds=60,
    ) == 6
    assert trigger_retry_policy.classify_exception.__module__.startswith("agent_core.")


def test_trigger_docker_build_copies_core_package_for_shared_imports():
    repo_root = Path(__file__).resolve().parents[1]
    dockerfile = (repo_root / "infra" / "agent_trigger" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "COPY agent_core/agent_core ./agent_core" in dockerfile
    assert "dockerfile: infra/agent_trigger/Dockerfile" in compose
    assert "PLANNING_AGENT_CORE_URL: http://planning-agent-core:8000" in compose
    assert "planning-agent-core:\n        condition: service_started" in compose


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any] | None]):
        self.rows = rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0)

    def fetchall(self):
        rows = self.rows
        self.rows = []
        return rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self.cursor_instance = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def cursor(self):
        return self.cursor_instance


def test_trigger_event_store_inserts_job_only_for_new_event(monkeypatch):
    trigger_storage = _import_trigger_module(monkeypatch, "app.storage")
    cursor = FakeCursor([{"id": "event-1"}])
    store = trigger_storage.EventStore("postgresql://example")
    store._connect = lambda: FakeConnection(cursor)

    result = store.insert_event(
        source_tool="openproject",
        event_type="work_package.updated",
        external_project_id="12",
        external_work_package_id="34",
        external_comment_id=None,
        idempotency_key="openproject:test",
        headers={},
        payload={},
    )

    assert result == trigger_storage.StoredEvent(event_id="event-1", created=True)
    assert any("INSERT INTO agent_jobs" in sql for sql, _ in cursor.executed)


def test_trigger_event_store_returns_existing_event_without_new_job(monkeypatch):
    trigger_storage = _import_trigger_module(monkeypatch, "app.storage")
    cursor = FakeCursor([None, {"id": "event-1"}])
    store = trigger_storage.EventStore("postgresql://example")
    store._connect = lambda: FakeConnection(cursor)

    result = store.insert_event(
        source_tool="openproject",
        event_type="work_package.updated",
        external_project_id="12",
        external_work_package_id="34",
        external_comment_id=None,
        idempotency_key="openproject:test",
        headers={},
        payload={},
    )

    assert result == trigger_storage.StoredEvent(event_id="event-1", created=False)
    assert not any("INSERT INTO agent_jobs" in sql for sql, _ in cursor.executed)
    assert any("WHERE idempotency_key = %s" in sql for sql, _ in cursor.executed)


def test_trigger_event_store_claims_available_job_with_lease(monkeypatch):
    trigger_storage = _import_trigger_module(monkeypatch, "app.storage")
    cursor = FakeCursor([{"attempt_count": 2}])
    store = trigger_storage.EventStore("postgresql://example")
    store._connect = lambda: FakeConnection(cursor)

    result = store.claim_event("event-1", lease_owner="worker-a", lease_seconds=300)

    assert result == trigger_storage.JobLease(event_id="event-1", attempt_count=2)
    assert any("lease_owner = %s" in sql for sql, _ in cursor.executed)
    assert any("retry_at IS NULL OR retry_at <= now()" in sql for sql, _ in cursor.executed)
    assert any("processing_status = 'processing'" in sql for sql, _ in cursor.executed)


def test_trigger_event_store_records_retry_and_dead_letter(monkeypatch):
    trigger_storage = _import_trigger_module(monkeypatch, "app.storage")
    retry_cursor = FakeCursor([])
    retry_store = trigger_storage.EventStore("postgresql://example")
    retry_store._connect = lambda: FakeConnection(retry_cursor)
    retry_at = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)

    retry_store.mark_retrying(
        "event-1",
        error_message="connection refused",
        retry_at=retry_at,
        retry_category="dependency_unavailable",
    )

    assert any("processing_status = 'pending'" in sql for sql, _ in retry_cursor.executed)
    assert any("status = 'queued'" in sql for sql, _ in retry_cursor.executed)
    assert any("last_error = %s::jsonb" in sql for sql, _ in retry_cursor.executed)

    dead_cursor = FakeCursor([])
    dead_store = trigger_storage.EventStore("postgresql://example")
    dead_store._connect = lambda: FakeConnection(dead_cursor)

    dead_store.mark_dead_letter(
        "event-1",
        error_message="bad payload",
        retry_category="invalid_input",
        retryable=False,
    )

    assert any("processing_status = 'dead_letter'" in sql for sql, _ in dead_cursor.executed)
    assert any("status = 'dead_letter'" in sql for sql, _ in dead_cursor.executed)


def test_trigger_event_store_lists_recoverable_jobs(monkeypatch):
    trigger_storage = _import_trigger_module(monkeypatch, "app.storage")
    cursor = FakeCursor([{"event_id": "event-1"}, {"event_id": "event-2"}])
    store = trigger_storage.EventStore("postgresql://example")
    store._connect = lambda: FakeConnection(cursor)

    result = store.list_recoverable_event_ids(limit=10)

    assert result == ["event-1", "event-2"]
    assert any("lease_expires_at < now()" in sql for sql, _ in cursor.executed)


class FakeStore:
    def __init__(self, stored_event):
        self.stored_event = stored_event
        self.calls: list[dict[str, Any]] = []

    def insert_event(self, **kwargs):
        self.calls.append(kwargs)
        return self.stored_event


class FakeRedis:
    def __init__(self):
        self.items: list[tuple[str, str]] = []

    def lpush(self, queue_name: str, event_id: str):
        self.items.append((queue_name, event_id))


def test_trigger_webhook_enqueues_only_new_events(monkeypatch):
    trigger_main = _import_trigger_module(monkeypatch, "app.main")
    trigger_storage = _import_trigger_module(monkeypatch, "app.storage")
    fake_store = FakeStore(trigger_storage.StoredEvent(event_id="event-1", created=True))
    fake_redis = FakeRedis()
    monkeypatch.setattr(trigger_main, "store", fake_store)
    monkeypatch.setattr(trigger_main, "redis_client", fake_redis)

    response = TestClient(trigger_main.app).post(
        "/webhooks/openproject",
        json={"action": "work_package.updated", "work_package_id": 34},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["queued"] is True
    assert fake_redis.items == [(trigger_main.settings.REDIS_QUEUE, "event-1")]
    assert fake_store.calls[0]["idempotency_key"].startswith("openproject:")


def test_trigger_webhook_does_not_enqueue_duplicate_events(monkeypatch):
    trigger_main = _import_trigger_module(monkeypatch, "app.main")
    trigger_storage = _import_trigger_module(monkeypatch, "app.storage")
    fake_store = FakeStore(trigger_storage.StoredEvent(event_id="event-1", created=False))
    fake_redis = FakeRedis()
    monkeypatch.setattr(trigger_main, "store", fake_store)
    monkeypatch.setattr(trigger_main, "redis_client", fake_redis)

    response = TestClient(trigger_main.app).post(
        "/webhooks/openproject",
        json={"action": "work_package.updated", "work_package_id": 34},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"
    assert response.json()["queued"] is False
    assert fake_redis.items == []


class FakeWorkerStore:
    def __init__(self, lease, event):
        self.lease = lease
        self.event = event
        self.retry_calls: list[dict[str, Any]] = []
        self.dead_letter_calls: list[dict[str, Any]] = []
        self.processed_calls: list[str] = []

    def claim_event(self, event_id: str, *, lease_owner: str, lease_seconds: int):
        self.claim_call = {
            "event_id": event_id,
            "lease_owner": lease_owner,
            "lease_seconds": lease_seconds,
        }
        return self.lease

    def get_event(self, event_id: str):
        return self.event

    def mark_processed(self, event_id: str):
        self.processed_calls.append(event_id)

    def mark_retrying(self, event_id: str, **kwargs):
        self.retry_calls.append({"event_id": event_id, **kwargs})

    def mark_dead_letter(self, event_id: str, **kwargs):
        self.dead_letter_calls.append({"event_id": event_id, **kwargs})


class FakeCoreClient:
    def __init__(self, result: dict[str, Any] | None = None, error: Exception | None = None):
        self.result = result or {"action": "context_sync_only"}
        self.error = error
        self.calls: list[str] = []

    def orchestrate_event(self, event_id: str):
        self.calls.append(event_id)
        if self.error:
            raise self.error
        return self.result


def test_trigger_worker_delegates_claimed_event_to_core(monkeypatch):
    trigger_worker = _import_trigger_module(monkeypatch, "app.worker")
    trigger_storage = _import_trigger_module(monkeypatch, "app.storage")
    core_client = FakeCoreClient(result={"action": "resume_planning"})
    store = FakeWorkerStore(
        lease=trigger_storage.JobLease(event_id="event-1", attempt_count=1),
        event={},
    )
    monkeypatch.setattr(trigger_worker.settings, "WORKER_ID", "worker-a")
    monkeypatch.setattr(trigger_worker.settings, "WORKER_LEASE_SECONDS", 120)

    result = trigger_worker.process_event(
        "event-1",
        store=store,
        core_client=core_client,
    )

    assert result.core_result == {"action": "resume_planning"}
    assert core_client.calls == ["event-1"]
    assert store.claim_call == {
        "event_id": "event-1",
        "lease_owner": "worker-a",
        "lease_seconds": 120,
    }
    assert store.processed_calls == ["event-1"]
    assert store.retry_calls == []
    assert store.dead_letter_calls == []


def test_trigger_worker_schedules_retry_for_transient_failures(monkeypatch):
    trigger_worker = _import_trigger_module(monkeypatch, "app.worker")
    trigger_storage = _import_trigger_module(monkeypatch, "app.storage")

    store = FakeWorkerStore(
        lease=trigger_storage.JobLease(event_id="event-1", attempt_count=2),
        event={},
    )
    monkeypatch.setattr(trigger_worker.settings, "WORKER_ID", "worker-a")
    monkeypatch.setattr(trigger_worker.settings, "WORKER_LEASE_SECONDS", 120)
    monkeypatch.setattr(trigger_worker.settings, "WORKER_MAX_EVENT_ATTEMPTS", 5)
    monkeypatch.setattr(trigger_worker.settings, "WORKER_RETRY_BASE_SECONDS", 3)
    monkeypatch.setattr(trigger_worker.settings, "WORKER_RETRY_MAX_SECONDS", 60)

    result = trigger_worker.process_event(
        "event-1",
        store=store,
        core_client=FakeCoreClient(error=TimeoutError("timed out")),
    )

    assert result.requeue_after_seconds == 6
    assert store.claim_call == {
        "event_id": "event-1",
        "lease_owner": "worker-a",
        "lease_seconds": 120,
    }
    assert store.retry_calls[0]["retry_category"] == RetryCategory.TRANSIENT_NETWORK
    assert store.retry_calls[0]["retry_at"] > datetime.now(timezone.utc)
    assert store.dead_letter_calls == []
    assert store.processed_calls == []


def test_trigger_worker_dead_letters_terminal_failures(monkeypatch):
    trigger_worker = _import_trigger_module(monkeypatch, "app.worker")
    trigger_storage = _import_trigger_module(monkeypatch, "app.storage")
    store = FakeWorkerStore(
        lease=trigger_storage.JobLease(event_id="event-1", attempt_count=1),
        event={},
    )

    result = trigger_worker.process_event(
        "event-1",
        store=store,
        core_client=FakeCoreClient(error=ValueError("bad event")),
    )

    assert result.requeue_after_seconds is None
    assert store.retry_calls == []
    assert store.dead_letter_calls[0]["retry_category"] == RetryCategory.INVALID_INPUT
    assert store.dead_letter_calls[0]["retryable"] is False
    assert store.processed_calls == []
