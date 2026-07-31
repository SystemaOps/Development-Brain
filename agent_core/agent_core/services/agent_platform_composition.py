from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.adapters.openproject import OpenProjectClient
from agent_core.agent_platform.adapters.openproject import (
    ManagedWorkPackageGateway,
    WorkPackageGateway,
)
from planning_agent_core.agent_platform.config import (
    AgentPlatformConfig,
    load_agent_platform_config,
)
from planning_agent_core.agent_platform.runtime import AgentDependencyContainer
from planning_agent_core.persistence.agent_platform import (
    SqlAlchemyAgentCheckpointStore,
    SqlAlchemyAgentResultStore,
)
from agent_core.persistence.agent_flows import SqlAlchemyAgentFlowStore
from agent_core.persistence.agent_transition_context import (
    SqlAlchemyAgentTransitionContextStore,
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
from agent_core.services.agent_platform_service import (
    AgentPlatformService,
    create_agent_platform_service,
)
from agent_core.services.agent_transition_resolver import (
    ApplicationAgentTransitionResolver,
)
from agent_core.services.coding_service import CodingService
from agent_core.services.planning_service import PlanningService
from agent_core.services.repository_analysis_service import (
    RepositoryAnalysisService,
)


def create_agent_platform_service_for_db(
    db: AsyncSession,
    *,
    platform_config: AgentPlatformConfig | None = None,
    work_package_gateway: WorkPackageGateway | None = None,
) -> AgentPlatformService:
    resolved_config = platform_config or load_agent_platform_config()
    checkpoint_store = SqlAlchemyAgentCheckpointStore(db)
    result_store = SqlAlchemyAgentResultStore(db)
    resolved_work_package_gateway = work_package_gateway
    if resolved_work_package_gateway is None:
        artifact_store = SqlAlchemyOpenProjectArtifactStore(db)
        outbound_store = SqlAlchemyOpenProjectOutboundStore(db)
        reconciliation_store = SqlAlchemyOpenProjectReconciliationStore(db)
        resolved_work_package_gateway = ManagedWorkPackageGateway(
            lambda: OpenProjectClient(
                artifact_store=artifact_store,
                outbound_store=outbound_store,
                reconciliation_store=reconciliation_store,
            )
        )
    dependencies = AgentDependencyContainer(
        db=db,
        planning_service=PlanningService(db),
        coding_service=CodingService(db),
        repository_service=RepositoryAnalysisService(db),
        work_package_gateway=resolved_work_package_gateway,
        checkpoint_store=checkpoint_store,
        result_store=result_store,
    )
    transition_resolver = ApplicationAgentTransitionResolver(
        context_store=SqlAlchemyAgentTransitionContextStore(db),
        config=resolved_config,
    )
    return create_agent_platform_service(
        dependencies,
        transition_resolver=transition_resolver,
        flow_store=SqlAlchemyAgentFlowStore(db),
        flow_lease_seconds=resolved_config.flow_runtime.lease_seconds,
        flow_recovery_enabled=resolved_config.flow_runtime.recovery_enabled,
    )
