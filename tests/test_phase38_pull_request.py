"""Phase 38 golden tests and completion gate.

Pull Request Runtime Integration: the PullRequestPort is wired through the
composition root (38.1), GitLab MR is the reference provider adapter (38.2),
PR creation is gated on verification PASS + policy permission (38.3), an
observation is created and projected to the work-management task (38.4), and
a merge event normalizes to PullRequestMerged -> RepositoryRevisionChanged ->
re-ingestion (38.5).
"""

from __future__ import annotations

import json
import urllib.request
import uuid
from unittest.mock import patch

import pytest

from brain.adapters.pull_request.gitlab import GitLabPullRequestAdapter
from brain.application.pull_request_service import PullRequestService
from brain.bootstrap.container import create_brain_container
from brain.bootstrap.settings import (
    AutomationPolicySettings,
    BrainSettings,
    DocumentationSettings,
    Neo4jSettings,
    PostgresSettings,
    PullRequestSettings,
    RedisSettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)
from brain.domain.events import EventType
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import new_workflow_id
from brain.domain.projects import Project
from brain.domain.repositories import Repository
from brain.domain.verification import VerificationResult, VerificationVerdict
from brain.domain.work_items import WorkItem
from tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable("postgresql+asyncpg://postgres:postgres@localhost:5432/brain"),
    reason="PostgreSQL is not available; start it with: docker compose up -d",
)


def _settings(
    pull_requests: PullRequestSettings | None = None,
    automation: AutomationPolicySettings | None = None,
) -> BrainSettings:
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
        pull_requests=pull_requests or PullRequestSettings(provider="fake"),
        automation=automation or AutomationPolicySettings(auto_create_pr=True),
    )


async def _seed(container) -> tuple[Project, WorkItem, Repository]:
    project = Project(name="pr-run")
    await container.repositories.projects.create(project)
    repository = Repository(
        project_id=project.id,
        name="repo",
        clone_url="https://gitlab.example.com/team/repo.git",
        default_branch="main",
    )
    await container.repositories.repositories.create(repository)
    work_item = WorkItem(
        project_id=project.id,
        title="implement login",
        description="add authentication",
        external_refs=[
            ExternalReference(
                provider="openproject",
                external_id="42",
                external_type="task",
            )
        ],
    )
    await container.repositories.work_items.create(work_item)
    return project, work_item, repository


def _execution_with_pass(container, work_item: WorkItem):
    from brain.domain.executions import Execution, ExecutionStatus
    from brain.domain.identity import new_actor_id

    execution = Execution(
        workflow_id=new_workflow_id(),
        work_item_id=work_item.id,
        executor_id=new_actor_id(),
        status=ExecutionStatus.COMPLETED,
        working_branch="brain/wi/deadbeef",
    )
    import asyncio

    return asyncio.run(container.repositories.executions.create(execution)), execution


async def test_gate_verified_code_creates_pr() -> None:
    """Verified + policy-permitted code creates a PR through the fake (38.3)."""
    container = await create_brain_container(_settings())
    try:
        _, work_item, _ = await _seed(container)
        from brain.domain.executions import Execution, ExecutionStatus
        from brain.domain.identity import new_actor_id

        execution = Execution(
            workflow_id=new_workflow_id(),
            work_item_id=work_item.id,
            executor_id=new_actor_id(),
            status=ExecutionStatus.COMPLETED,
            working_branch="brain/wi/deadbeef",
        )
        await container.repositories.executions.create(execution)
        await container.repositories.verification_results.create(
            VerificationResult(
                execution_id=execution.id,
                verdict=VerificationVerdict.PASS,
            )
        )
        service = container.services["pull_request_service"]
        assert isinstance(service, PullRequestService)
        result = await service.create_pull_request(
            execution_id=execution.id, work_item_id=work_item.id
        )
        assert result.created is True
        assert result.external_ref is not None
        assert result.external_ref.external_id.startswith("PR-")
        assert result.observation_id is not None

        # Task 38.4: the observation exists with the MR body.
        observations = await container.repositories.observations.list_by_project(
            work_item.project_id
        )
        assert any("Merge Request" in o.body for o in observations)
    finally:
        await container.close()


async def test_pr_readiness_blocks_without_pass() -> None:
    """Without a PASS verdict the provider is never called (38.3)."""
    container = await create_brain_container(_settings())
    try:
        _, work_item, _ = await _seed(container)
        from brain.domain.executions import Execution, ExecutionStatus
        from brain.domain.identity import new_actor_id

        execution = Execution(
            workflow_id=new_workflow_id(),
            work_item_id=work_item.id,
            executor_id=new_actor_id(),
            status=ExecutionStatus.COMPLETED,
        )
        await container.repositories.executions.create(execution)
        await container.repositories.verification_results.create(
            VerificationResult(
                execution_id=execution.id,
                verdict=VerificationVerdict.FAIL,
            )
        )
        service = container.services["pull_request_service"]
        assert isinstance(service, PullRequestService)
        result = await service.create_pull_request(
            execution_id=execution.id, work_item_id=work_item.id
        )
        assert result.created is False
        assert "verification verdict is not PASS" in result.reasons
    finally:
        await container.close()


async def test_merge_event_normalizes_and_enqueues_reingestion() -> None:
    """Merge -> PullRequestMerged -> RepositoryRevisionChanged (38.5)."""
    container = await create_brain_container(_settings())
    try:
        service = container.services["pull_request_service"]
        assert isinstance(service, PullRequestService)
        ref = ExternalReference(
            provider="gitlab",
            external_id="7",
            external_type="merge_request",
            namespace="1",
        )
        revision_event = await service.handle_merge(ref)
        assert revision_event.event_type == EventType.REPOSITORY_REVISION_CHANGED

        events = container.services["events"]
        from brain.adapters.in_memory.event_bus import InMemoryEventBus

        assert isinstance(events, InMemoryEventBus)
        types = [e.event_type for e in events.published]
        assert EventType.PULL_REQUEST_MERGED in types
        assert EventType.REPOSITORY_REVISION_CHANGED in types

        # Re-ingestion is enqueued on the command queue.
        queue = container.services["command_queue"]
        from brain.adapters.in_memory.commands import InMemoryCommandQueue

        assert isinstance(queue, InMemoryCommandQueue)
        assert await queue.pending_count() >= 1
        # consume + acknowledge to verify the sync_repository command.
        command = await queue.consume(timeout_seconds=0.2)
        assert command is not None
        assert command.command_type.value == "sync_repository"
        await queue.acknowledge(command.command_id)
    finally:
        await container.close()


async def test_gitlab_webhook_normalizes_merge() -> None:
    """The GitLab webhook route normalizes a merge event (38.5)."""
    container = await create_brain_container(_settings())
    try:
        from starlette.requests import Request

        from brain.api.routes import webhooks

        payload = {
            "object_kind": "merge_request",
            "object_attributes": {
                "iid": "9",
                "state": "merged",
                "target_project_id": "1",
            },
        }
        # Exercise the normalization logic directly through the router
        # function with a minimal Request.
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/webhooks/gitlab",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
            "scheme": "http",
            "state": {"correlation_id": uuid.uuid4()},
        }

        async def receive() -> dict[str, object]:
            return {
                "type": "http.request",
                "body": json.dumps(payload).encode("utf-8"),
                "more_body": False,
            }

        request = Request(scope, receive=receive)
        from brain.bootstrap.container import BrainContainer

        def fake_get_container(req: Request) -> BrainContainer:
            return container

        with patch.object(webhooks, "get_container", fake_get_container):
            result = await webhooks.gitlab_webhook(request)
        assert result["event_type"] == "repository_revision_changed"
        assert result["external_id"] == "9"
    finally:
        await container.close()


async def test_gitlab_adapter_builds_urls_and_maps() -> None:
    """GitLab adapter: project resolution + reference mapping (38.2)."""
    from brain.domain.identity import new_project_id
    from brain.domain.repositories import Repository as DomainRepository

    repository = DomainRepository(
        project_id=new_project_id(),
        name="repo",
        clone_url="git@gitlab.example.com:team/repo.git",
    )
    adapter = GitLabPullRequestAdapter(base_url="http://gitlab:80", api_key="token")
    assert adapter._project_id == ""
    # Without a configured project id, the clone URL path is used.
    from brain.adapters.pull_request.gitlab import _project_from_repository

    assert _project_from_repository(repository) == "team/repo"


async def test_gitlab_adapter_creates_mr_via_http() -> None:
    """create_pull_request POSTs to the GitLab API (38.2)."""
    captured: dict[str, object] = {}

    class _FakeResponse:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return self._data

    def _fake_urlopen(request: object, timeout: int) -> _FakeResponse:
        del timeout
        assert isinstance(request, urllib.request.Request)
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = request.data
        return _FakeResponse(json.dumps({"iid": 11}).encode("utf-8"))

    from brain.domain.identity import new_project_id
    from brain.domain.repositories import Repository as DomainRepository

    repository = DomainRepository(
        project_id=new_project_id(),
        name="repo",
        clone_url="https://gitlab.example.com/team/repo.git",
    )
    adapter = GitLabPullRequestAdapter(
        base_url="http://gitlab:80", api_key="token", project_id="team/repo"
    )
    with patch.object(urllib.request, "urlopen", _fake_urlopen):
        ref = await adapter.create_pull_request(
            repository=repository,
            source_branch="brain/wi/deadbeef",
            target_branch="main",
            title="implement login",
            description="add auth",
        )
    assert captured["method"] == "POST"
    url = captured["url"]
    assert isinstance(url, str)
    assert url.endswith("/api/v4/projects/team%2Frepo/merge_requests")
    assert ref.provider == "gitlab"
    assert ref.external_id == "11"
    assert ref.external_type == "merge_request"


def test_gitlab_adapter_project_from_external_ref() -> None:
    from brain.domain.identity import new_project_id
    from brain.domain.repositories import Repository as DomainRepository

    repository = DomainRepository(
        project_id=new_project_id(),
        name="repo",
        clone_url="https://example.com/unused.git",
        external_refs=[
            ExternalReference(
                provider="gitlab",
                external_id="7",
                external_type="project",
            )
        ],
    )
    from brain.adapters.pull_request.gitlab import _project_from_repository

    assert _project_from_repository(repository) == "7"
