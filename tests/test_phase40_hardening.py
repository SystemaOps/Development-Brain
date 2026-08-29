"""Phase 40 golden tests and completion gate.

Production Hardening: the system is ready for controlled production-like
pilot use.

40.1 - API authentication with separate identities (human/service/webhook/
executor/admin).
40.2 - authorization covers project access, execution triggering,
observation resolution, PR creation, admin.
40.3 - webhook signatures/tokens are validated before normalization.
40.4 - credentials are never persisted as plaintext (hash-only keys).
40.5 - rate limiting protects expensive operations.
40.6 - concurrency controls prevent conflicting automated changes to the same
repository.
40.7 - audit trail records who/what triggered, executor, revision, changes,
verdict, observations, external tools.
40.8 - metrics expose latency, queue depth, execution outcomes, verification,
context tokens, provider availability, projection results.
40.9 - backup/rebuild strategy documented (docs/runtime/backup-and-rebuild.md).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from brain.api.auth import api_key_dependency, verify_webhook
from brain.application.audit import AuditService
from brain.application.authorization import AuthorizationError, AuthorizationService, Permission
from brain.application.metrics import MetricsService
from brain.application.rate_limiter import RateLimiter, RateLimitExceeded, RateLimitRule
from brain.application.workspace_locks import (
    InMemoryWorkspaceLockStore,
    WorkspaceLockManager,
)
from brain.bootstrap.container import create_brain_container
from brain.bootstrap.settings import (
    BrainSettings,
    DocumentationSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    SecuritySettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)
from brain.domain.audit import AuditAction
from brain.domain.identity import new_execution_id, new_repository_id
from brain.domain.identity_auth import Identity, IdentityRole, hash_api_key
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


def _settings(security: SecuritySettings | None = None) -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
        storage_semantic=WeaviateSettings(host="localhost"),
        storage_queue=RedisSettings(url="redis://localhost:6379/0"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
        security=security or SecuritySettings(),
    )


async def test_40_1_api_key_authentication_and_roles() -> None:
    """API keys authenticate with separate identities (40.1)."""
    container = await create_brain_container(
        _settings(
            SecuritySettings(
                api_keys="admin-key=admin:brain-admin-secret;ci=service:brain-ci-secret"
            )
        )
    )
    try:
        store = container.services["api_key_store"]
        from brain.adapters.in_memory.api_keys import InMemoryApiKeyStore

        assert isinstance(store, InMemoryApiKeyStore)
        admin = await store.authenticate("brain-admin-secret")
        assert admin is not None and admin.role == IdentityRole.ADMIN
        service = await store.authenticate("brain-ci-secret")
        assert service is not None and service.role == IdentityRole.SERVICE
        # Unknown keys never authenticate.
        assert await store.authenticate("brain-nope") is None
        # Only the hash is stored.
        for key in await store.list():
            assert key.key_hash == hash_api_key(
                "brain-admin-secret" if "admin" in key.name else "brain-ci-secret"
            )
            assert "brain-" not in key.key_hash
    finally:
        await container.close()


async def test_40_2_authorization_matrix() -> None:
    """Authorization covers the required operations (40.2)."""
    auth = AuthorizationService()
    human = Identity(name="h", role=IdentityRole.HUMAN)
    service = Identity(name="s", role=IdentityRole.SERVICE)
    webhook = Identity(name="w", role=IdentityRole.WEBHOOK)
    executor = Identity(name="e", role=IdentityRole.EXECUTOR)
    admin = Identity(name="a", role=IdentityRole.ADMIN)

    for identity in (human, service):
        auth.allow(identity, Permission.PROJECT_ACCESS)
        auth.allow(identity, Permission.EXECUTION_TRIGGER)
        auth.allow(identity, Permission.OBSERVATION_RESOLVE)
        auth.allow(identity, Permission.PR_CREATE)
    auth.allow(admin, Permission.ADMIN)
    auth.allow(webhook, Permission.WEBHOOK_DELIVERY)
    auth.allow(executor, Permission.EXECUTOR_CONTEXT)

    with pytest.raises(AuthorizationError):
        auth.allow(webhook, Permission.EXECUTION_TRIGGER)
    with pytest.raises(AuthorizationError):
        auth.allow(executor, Permission.PR_CREATE)
    with pytest.raises(AuthorizationError):
        auth.allow(human, Permission.ADMIN)


async def test_40_3_webhook_signature_validation() -> None:
    """OpenProject HMAC signature validated before normalization (40.3)."""
    container = await create_brain_container(
        _settings(SecuritySettings(webhook_openproject_secret="op-secret"))
    )
    try:
        from starlette.requests import Request

        body = json.dumps(
            {"eventType": "work_package:updated", "work_package": {"id": "1"}}
        ).encode()

        def _request(headers: list[tuple[bytes, bytes]]) -> Request:
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/webhooks/openproject",
                "headers": headers,
                "query_string": b"",
                "client": ("127.0.0.1", 1),
                "server": ("test", 80),
                "scheme": "http",
                "state": {"correlation_id": uuid.uuid4()},
            }

            async def receive() -> dict[str, object]:
                return {"type": "http.request", "body": body, "more_body": False}

            return Request(scope, receive=receive)

        valid = "sha256=" + hmac.new(b"op-secret", body, hashlib.sha256).hexdigest()
        from fastapi import HTTPException

        with patch("brain.api.auth.get_container", lambda req: container):
            good = await verify_webhook("openproject")(
                _request([(b"x-openproject-signature", valid.encode())])
            )
            assert good is not None
            with pytest.raises(HTTPException):
                await verify_webhook("openproject")(
                    _request([(b"x-openproject-signature", b"sha256=deadbeef")])
                )
            with pytest.raises(HTTPException):
                await verify_webhook("openproject")(_request([]))
    finally:
        await container.close()


async def test_40_4_secrets_never_persisted_plaintext() -> None:
    """Credential material is never stored in the database (40.4)."""
    container = await create_brain_container(
        _settings(SecuritySettings(api_keys="svc=service:brain-svc-secret"))
    )
    try:
        # No api key plaintext anywhere in the audit/state repos.
        from brain.adapters.postgresql.repositories import PostgresAuditLog

        audits = container.repositories.audit_log
        assert isinstance(audits, PostgresAuditLog)
        for event in await audits.list():
            assert "brain-svc-secret" not in json.dumps(event.details)
        store = container.services["api_key_store"]
        from brain.adapters.in_memory.api_keys import InMemoryApiKeyStore

        assert isinstance(store, InMemoryApiKeyStore)
        keys = await store.list()
        assert all("brain-svc-secret" not in key.key_hash for key in keys)
    finally:
        await container.close()


async def test_40_5_rate_limiting_expensive_operations() -> None:
    """Rate limiting protects analysis/context/execution/verification (40.5)."""
    limiter = RateLimiter({"context_build": RateLimitRule(limit=3, window_seconds=60)})
    identity = Identity(name="ci", role=IdentityRole.SERVICE)
    for _ in range(3):
        limiter.check(identity, "context_build")
    with pytest.raises(RateLimitExceeded):
        limiter.check(identity, "context_build")
    assert limiter.count(identity, "context_build") == 3


async def test_40_6_concurrency_lock_prevents_conflicts() -> None:
    """Only one execution may change a repository at a time (40.6)."""
    manager = WorkspaceLockManager(store=InMemoryWorkspaceLockStore())
    repo = new_repository_id()
    first = new_execution_id()
    second = new_execution_id()

    lock = await manager.try_acquire(repo, first, "brain/wi/a")
    assert lock is not None
    # A conflicting execution cannot acquire the same repository.
    assert await manager.try_acquire(repo, second, "brain/wi/b") is None
    assert await manager.release(repo, second) is False
    assert await manager.release(repo, first) is True
    # After release the next execution may proceed.
    assert await manager.try_acquire(repo, second, "brain/wi/b") is not None


async def test_40_7_audit_trail_recorded() -> None:
    """Audit records who/what triggered + execution details (40.7)."""
    container = await create_brain_container(_settings())
    try:
        audit = container.services["audit"]
        assert isinstance(audit, AuditService)
        await audit.record(
            action=AuditAction.EXECUTION_COMPLETED,
            actor="trigger:webhook",
            actor_role="webhook",
            project_id=uuid.uuid4(),
            details={
                "executor": "pi",
                "base_revision": "abc123",
                "working_branch": "brain/wi/x",
                "changed_files": ["src/auth/service.py"],
                "verdict": "pass",
                "observation_published": "42",
                "external_tool": "openproject",
            },
        )
        events = await audit.list()
        assert events and events[-1].action == AuditAction.EXECUTION_COMPLETED
        latest = events[-1]
        assert latest.details["executor"] == "pi"
        assert latest.details["base_revision"] == "abc123"
        assert latest.details["verdict"] == "pass"
        assert latest.details["external_tool"] == "openproject"

        # The audit log is persisted in Postgres.
        from brain.adapters.postgresql.repositories import PostgresAuditLog

        persisted = container.repositories.audit_log
        assert isinstance(persisted, PostgresAuditLog)
        events = await persisted.list(action="execution_completed")
        assert events
    finally:
        await container.close()


async def test_40_8_metrics_snapshot() -> None:
    """Metrics cover latency, execution, verification, context, providers (40.8)."""
    metrics = MetricsService()
    metrics.observe("api_request_latency_seconds", 0.12)
    metrics.inc("execution_completed_total", labels='status="completed"')
    metrics.inc("verification_failed_total")
    metrics.inc("context_builds_total")
    metrics.set_gauge("queue_depth", 3)
    metrics.inc("projection_succeeded_total")
    metrics.inc("provider_unavailable_total", labels='provider="docling"')

    snapshot = metrics.snapshot()
    assert snapshot.histograms["api_request_latency_seconds"]["total"] == 1
    assert snapshot.counters['execution_completed_total{status="completed"}'] == 1
    assert snapshot.counters["verification_failed_total"] == 1
    assert snapshot.counters["context_builds_total"] == 1
    assert snapshot.gauges["queue_depth"] == 3
    assert snapshot.counters["projection_succeeded_total"] == 1
    assert snapshot.counters['provider_unavailable_total{provider="docling"}'] == 1


async def test_40_9_backup_doc_exists() -> None:
    """Backup/rebuild strategy is documented (40.9)."""
    doc = Path(__file__).parent.parent / "docs" / "runtime" / "backup-and-rebuild.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "Postgres" in text and "Neo4j" in text and "Weaviate" in text and "MinIO" in text
    assert "canonical" in text and "rebuildable" in text


async def test_40_api_keys_required_when_enabled() -> None:
    """With auth enabled, unauthenticated requests are rejected (40.1)."""
    container = await create_brain_container(
        _settings(SecuritySettings(api_keys="svc=service:brain-svc-secret"))
    )
    try:
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/health",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
            "scheme": "http",
            "state": {"correlation_id": uuid.uuid4()},
        }

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        with patch("brain.api.auth.get_container", lambda req: container):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as excinfo:
                await api_key_dependency(Request(scope, receive=receive))
            assert excinfo.value.status_code == 401
    finally:
        await container.close()
