"""Phase 2 tests: project provisioning adapters.

OpenProject ``create_project`` (POST /api/v3/projects), GitLab project
creation (POST /api/v4/projects) and XWiki space creation (PUT .../spaces)
normalize provider payloads into canonical ``ExternalReference`` records.
"""

from __future__ import annotations

import json
import uuid

from brain.adapters.documentation.xwiki import XWikiDocumentationAdapter
from brain.adapters.git.gitlab_provisioning import GitLabProjectProvisioningAdapter, _project_path
from brain.adapters.work_management.openproject import OpenProjectAdapter
from brain.adapters.work_management.openproject_http import _project_identifier
from brain.domain.identity import ProjectId

# --- OpenProject ------------------------------------------------------------


class _FakeOpenProjectTransport:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    async def create_project(self, name: str, description: str | None = None) -> dict[str, object]:
        self.created.append({"name": name, "description": description})
        return {"id": 41, "name": name, "identifier": _project_identifier(name)}

    # unused surface
    async def get_work_package(self, external_id: str) -> dict[str, object]:
        raise NotImplementedError

    async def list_updated_work_packages(self, since: object) -> list[dict[str, object]]:
        raise NotImplementedError

    async def list_updated_work_packages_page(
        self, since, *, offset=1, page_size=100, project_id=None
    ):
        raise NotImplementedError

    async def list_projects(self) -> list[dict[str, object]]:
        raise NotImplementedError

    async def list_project_work_packages(self, project_external_id, *, offset=1, page_size=100):
        raise NotImplementedError

    async def get_activities(self, external_id: str) -> list[dict[str, object]]:
        raise NotImplementedError

    async def create_work_package(self, payload: dict[str, object]) -> dict[str, object]:
        raise NotImplementedError

    async def update_status(self, external_id: str, status: str) -> None:
        raise NotImplementedError

    async def post_comment(self, external_id: str, body: str) -> object:
        raise NotImplementedError

    async def link_pull_request(self, external_id: str, pr_ref: str) -> None:
        raise NotImplementedError


async def test_gate_openproject_create_project() -> None:
    transport = _FakeOpenProjectTransport()
    adapter = OpenProjectAdapter(transport=transport, project_id=ProjectId(uuid.uuid4()))
    ref = await adapter.create_project("ADAS Platform", "platform docs")
    assert ref.provider == "openproject"
    assert ref.external_type == "project"
    assert ref.external_id == "41"
    assert transport.created[0]["name"] == "ADAS Platform"


def test_gate_openproject_identifier_slug() -> None:
    assert _project_identifier("ADAS Platform") == "adas_platform"
    assert _project_identifier("Project  -  X!") == "project_x"
    assert _project_identifier("!!!") == "project"
    assert _project_identifier("already_ok") == "already_ok"


# --- GitLab -----------------------------------------------------------------


def _fake_urlopen(response_payload: dict[str, object]):
    """Monkeypatch target: returns a fake context-manager urllib response."""

    class _FakeResponse:
        def __init__(self) -> None:
            self.status = 201

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(response_payload).encode("utf-8")

    return lambda request, timeout=None: _FakeResponse()


async def test_gate_gitlab_create_project(monkeypatch) -> None:
    import urllib.request

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _fake_urlopen(
            {
                "id": 812,
                "path_with_namespace": "group/adas-platform",
                "path": "adas-platform",
                "name": "ADAS Platform",
            }
        ),
    )
    adapter = GitLabProjectProvisioningAdapter("http://localhost:8929", api_key="token")
    ref = await adapter.create_project("ADAS Platform", "platform docs")
    assert ref.provider == "gitlab"
    assert ref.external_id == "812"
    assert ref.namespace == "group/adas-platform"


def test_gate_gitlab_project_path_slug() -> None:
    assert _project_path("ADAS Platform") == "adas-platform"
    assert _project_path("Project  -  X!") == "project-x"
    assert _project_path("!!!") == "project"


# --- XWiki ------------------------------------------------------------------


class _FakeXWikiTransport:
    def __init__(self) -> None:
        self.created: list[str] = []

    async def create_space(self, space: str) -> dict[str, object]:
        self.created.append(space)
        return {"name": space, "type": "space"}

    # unused surface
    async def get_page(self, page_id: str) -> dict[str, object]:
        raise NotImplementedError

    async def get_page_version(self, page_id: str, version: str) -> dict[str, object]:
        raise NotImplementedError

    async def list_page_changes(self, page_id: str) -> list[dict[str, object]]:
        raise NotImplementedError

    async def get_attachments(self, page_id: str) -> list[dict[str, object]]:
        raise NotImplementedError

    async def get_children(self, page_id: str) -> list[dict[str, object]]:
        raise NotImplementedError

    async def get_links(self, page_id: str) -> list[str]:
        raise NotImplementedError

    async def list_changed_pages(self, spaces, since=None, *, page_size=50):
        raise NotImplementedError


async def test_gate_xwiki_create_space() -> None:
    transport = _FakeXWikiTransport()
    adapter = XWikiDocumentationAdapter(transport=transport, wiki="xwiki")
    ref = await adapter.create_space("ADASPlatform")
    assert ref.provider == "xwiki"
    assert ref.external_type == "space"
    assert ref.external_id == "ADASPlatform"
    assert ref.namespace == "xwiki"
    assert transport.created == ["ADASPlatform"]
