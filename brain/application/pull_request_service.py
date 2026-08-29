"""Pull request runtime service (Phase 38).

Task 38.3 - PR readiness: a PR/MR is only created when verification passed and
policy permits it.
Task 38.4 - PR observation: after creation an observation is journaled and
projected to the work-management task.
Task 38.5 - Merge event: a provider merge event normalizes to
PullRequestMerged -> RepositoryRevisionChanged -> re-ingestion enqueued.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from brain.application.observations import ObservationService
from brain.bootstrap.container import BrainContainer
from brain.domain.events import EventEnvelope, EventType
from brain.domain.external_reference import ExternalReference
from brain.domain.identity import ExecutionId, WorkItemId
from brain.domain.observations import Observation, ObservationType
from brain.domain.work_items import WorkItem
from brain.ports.event_bus import EventBus

logger = logging.getLogger(__name__)


@dataclass
class PullRequestServiceResult:
    """Outcome of a PR creation attempt."""

    created: bool
    external_ref: ExternalReference | None = None
    observation_id: str | None = None
    reasons: list[str] = field(default_factory=list)


class PullRequestService:
    """Creates pull requests only when verification + policy allow it."""

    def __init__(self, *, container: BrainContainer) -> None:
        self._container = container

    async def create_pull_request(
        self,
        *,
        execution_id: ExecutionId,
        work_item_id: WorkItemId,
    ) -> PullRequestServiceResult:
        pr_port = self._container.pull_requests
        if pr_port is None:
            return PullRequestServiceResult(
                created=False, reasons=["no pull request provider configured"]
            )
        execution = await self._container.repositories.executions.get(execution_id)
        if execution is None:
            return PullRequestServiceResult(created=False, reasons=["execution not found"])
        work_item = await self._container.repositories.work_items.get(work_item_id)
        if work_item is None:
            return PullRequestServiceResult(created=False, reasons=["work item not found"])

        reasons: list[str] = []
        # Task 38.3: verification must have passed for this execution.
        if not await self._verification_passed(execution_id):
            reasons.append("verification verdict is not PASS")
        # Task 38.3: policy must permit PR creation.
        if not await self._policy_permits(work_item):
            reasons.append("policy does not permit pull request creation")
        if reasons:
            return PullRequestServiceResult(created=False, reasons=reasons)

        repositories = await self._container.repositories.repositories.list_by_project(
            work_item.project_id
        )
        if not repositories:
            return PullRequestServiceResult(
                created=False, reasons=["no repository for the work item"]
            )
        repository = repositories[0]

        ref = await pr_port.create_pull_request(
            repository=repository,
            source_branch=execution.working_branch or f"brain/{execution.id}",
            target_branch=repository.default_branch,
            title=work_item.title,
            description=work_item.description,
        )
        await self._events().publish(
            EventEnvelope(
                event_type=EventType.PULL_REQUEST_CREATED,
                project_id=work_item.project_id,
                correlation_id=execution.correlation_id,
                source="pull_request_service",
                payload={
                    "external_id": ref.external_id,
                    "provider": ref.provider,
                    "execution_id": str(execution.id),
                    "work_item_id": str(work_item.id),
                },
            )
        )

        # Task 38.4: journal the result as an observation.
        observation = await self._observations().create(
            project_id=work_item.project_id,
            observation_type=ObservationType.VERIFICATION_PASS,
            title="Pull request created",
            body=f"Verification passed. Merge Request !{ref.external_id} was created.",
            work_item_id=work_item.id,
            execution_id=execution.id,
            correlation_id=execution.correlation_id,
            dedup_key=f"pr-created:{execution.id}",
        )
        await self._project_to_task(observation, work_item)

        return PullRequestServiceResult(
            created=True,
            external_ref=ref,
            observation_id=str(observation.id),
            reasons=["verification passed; policy permitted"],
        )

    async def handle_merge(self, ref: ExternalReference) -> EventEnvelope:
        """Task 38.5: merge event -> revision changed -> re-ingestion."""
        events = self._events()
        merged = EventEnvelope(
            event_type=EventType.PULL_REQUEST_MERGED,
            source="pull_request_service",
            payload={
                "provider": ref.provider,
                "external_id": ref.external_id,
                "namespace": ref.namespace or "",
            },
        )
        revision_changed = EventEnvelope(
            event_type=EventType.REPOSITORY_REVISION_CHANGED,
            correlation_id=merged.correlation_id,
            causation_id=merged.event_id,
            source="pull_request_service",
            payload={"external_ref": ref.model_dump(mode="json")},
        )
        await events.publish(merged)
        await events.publish(revision_changed)
        await self._enqueue_reingestion(ref)
        return revision_changed

    async def _verification_passed(self, execution_id: ExecutionId) -> bool:
        results = await self._container.repositories.verification_results.list_by_execution(
            execution_id
        )
        return any(str(getattr(result, "verdict", "")).lower() == "pass" for result in results)

    async def _policy_permits(self, work_item: WorkItem) -> bool:
        policy = self._container.services["policy"]
        from brain.application.policy_service import PolicyService

        assert isinstance(policy, PolicyService)
        evaluation = await policy.evaluate(work_item)
        if not evaluation.allowed:
            return False
        from brain.domain.policies import ApprovalType

        return ApprovalType.PR not in evaluation.required_approvals

    async def _project_to_task(self, observation: Observation, work_item: WorkItem) -> None:
        target = _work_management_target(work_item)
        if target is None:
            return
        projection = self._container.services["observation_projection"]
        from brain.application.observation_projection import ObservationProjectionService

        assert isinstance(projection, ObservationProjectionService)
        try:
            await projection.project(observation, target)
        except Exception:  # noqa: BLE001 - projection is best-effort
            logger.warning("could not project PR observation to %s", target.provider, exc_info=True)

    def _observations(self) -> ObservationService:
        service = self._container.services["observations"]
        from brain.application.observations import ObservationService

        assert isinstance(service, ObservationService)
        return service

    def _events(self) -> EventBus:
        service = self._container.services["events"]
        from brain.ports.event_bus import EventBus

        assert isinstance(service, EventBus)
        return service

    async def _enqueue_reingestion(self, ref: ExternalReference) -> None:
        queue = self._container.services["command_queue"]
        from brain.domain.commands import CommandEnvelope, CommandType
        from brain.domain.identity import new_repository_id

        enqueue = getattr(queue, "enqueue", None)
        if enqueue is None:
            return
        await enqueue(
            CommandEnvelope(
                command_type=CommandType.SYNC_REPOSITORY,
                payload={
                    "repository_id": str(new_repository_id()),
                    "external_ref": ref.model_dump(mode="json"),
                },
            )
        )


def _work_management_target(work_item: WorkItem) -> ExternalReference | None:
    for ref in work_item.external_refs:
        if ref.external_type in {"task", "work_item", "issue"}:
            return ref
    return None


__all__ = ["PullRequestService", "PullRequestServiceResult"]
