"""Work management port (OpenProject / Jira / Linear / ...).

The brain core depends only on this Protocol; provider adapters translate
their native types to and from canonical ``WorkItem`` / ``ExternalReference``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from brain.domain.external_reference import ExternalReference
from brain.domain.identity import WorkItemId
from brain.domain.work_items import WorkItem


@runtime_checkable
class WorkManagementPort(Protocol):
    async def fetch_work_item(self, ref: ExternalReference) -> WorkItem: ...

    async def list_changed_work_items(self, since: datetime) -> list[WorkItem]: ...

    async def publish_work_item(self, work_item: WorkItem) -> ExternalReference: ...

    async def publish_status(self, work_item_id: WorkItemId, status: str) -> None: ...

    async def post_execution_result(self, work_item_id: WorkItemId, result: str) -> None: ...

    async def link_pull_request(
        self, work_item_id: WorkItemId, pr_ref: ExternalReference
    ) -> None: ...
