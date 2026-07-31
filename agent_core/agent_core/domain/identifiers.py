from __future__ import annotations

from typing import NewType

ProjectId = NewType("ProjectId", str)
RepositoryId = NewType("RepositoryId", str)
RequirementId = NewType("RequirementId", str)
PlanVersionId = NewType("PlanVersionId", str)
PlanNodeId = NewType("PlanNodeId", str)
TaskId = NewType("TaskId", str)
ExecutionId = NewType("ExecutionId", str)
ThreadId = NewType("ThreadId", str)
SkillRunId = NewType("SkillRunId", str)
WebhookEventId = NewType("WebhookEventId", str)
