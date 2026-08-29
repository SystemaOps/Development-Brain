"""Run the WorkManagementPort contract against both OpenProject and Jira adapters,
proving provider interchangeability."""

from __future__ import annotations

from datetime import datetime

import pytest

from brain.adapters.work_management.jira import JiraAdapter
from brain.adapters.work_management.openproject import OpenProjectAdapter
from brain.domain.identity import new_project_id
from brain.ports.work_management import WorkManagementPort
from tests.contracts.work_management import WorkManagementPortContract


class _FakeOpenProject:
    async def get_work_package(self, external_id: str) -> dict:
        return {
            "id": external_id,
            "subject": f"WP {external_id}",
            "description": "x",
            "status": "new",
        }

    async def list_updated_work_packages(self, since: datetime) -> list[dict]:
        return [{"id": "1", "subject": "Updated", "status": "in_progress"}]

    async def create_work_package(self, payload: dict) -> dict:
        return {"id": "99", "subject": payload.get("subject", "")}

    async def update_status(self, external_id: str, status: str) -> None:
        return None

    async def post_comment(self, external_id: str, body: str) -> None:
        return None

    async def link_pull_request(self, external_id: str, pr_ref: str) -> None:
        return None


class _FakeJira:
    async def get_issue(self, external_id: str) -> dict:
        return {
            "key": external_id,
            "summary": f"Issue {external_id}",
            "description": "x",
            "status": "new",
        }

    async def list_updated_issues(self, since: datetime) -> list[dict]:
        return [{"key": "A-1", "summary": "Updated", "status": "in_progress"}]

    async def create_issue(self, payload: dict) -> dict:
        return {"key": "A-99", "summary": payload.get("summary", "")}

    async def update_status(self, external_id: str, status: str) -> None:
        return None

    async def post_comment(self, external_id: str, body: str) -> None:
        return None

    async def link_pull_request(self, external_id: str, pr_ref: str) -> None:
        return None


class TestOpenProjectAdapter(WorkManagementPortContract):
    @pytest.fixture
    def work_management(self) -> WorkManagementPort:
        return OpenProjectAdapter(transport=_FakeOpenProject(), project_id=new_project_id())


class TestJiraAdapter(WorkManagementPortContract):
    @pytest.fixture
    def work_management(self) -> WorkManagementPort:
        return JiraAdapter(transport=_FakeJira(), project_id=new_project_id())
