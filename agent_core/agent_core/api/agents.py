from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SerializeAsAny
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.agent_platform.agents.base import AgentResult
from agent_core.agent_platform.agents.coding import CodingAgentRequest
from agent_core.agent_platform.agents.planning import PlanningAgentRequest
from agent_core.agent_platform.agents.verification import (
    VerificationAgentRequest,
    VerificationOverrideCommand,
)
from agent_core.agent_platform.config import AgentConfig, load_agent_platform_config
from agent_core.agent_platform.orchestration import (
    AgentExecutionRequest,
    AgentFlowApproval,
    AgentFlowLeaseConflictError,
    AgentFlowNotFoundError,
    AgentFlowPersistenceError,
    AgentFlowVersionConflictError,
    AgentRouteDecision,
    PersistedAgentFlow,
)
from agent_core.agent_platform.agents.base.errors import AgentValidationError
from agent_core.api.deps import get_db
from agent_core.services.agent_platform_composition import (
    create_agent_platform_service_for_db,
)

router = APIRouter(prefix="/v1/agents", tags=["agents"])

AgentExecutionRequestPayload = Annotated[
    PlanningAgentRequest | CodingAgentRequest | VerificationAgentRequest,
    Field(discriminator="agent_type"),
]


class AgentExecutePayload(BaseModel):
    request: AgentExecutionRequestPayload
    config: SerializeAsAny[AgentConfig] | None = None
    workflow_id: str | None = None
    correlation_id: str | None = None


class AgentExecutionResponse(BaseModel):
    persisted_result_id: UUID
    result: SerializeAsAny[AgentResult]
    route: AgentRouteDecision


class AgentFlowStartPayload(AgentExecutePayload):
    max_steps: int = Field(default=10, ge=1, le=100)


class AgentFlowResumePayload(BaseModel):
    expected_version: int = Field(ge=1)
    request: AgentExecutionRequestPayload | None = None
    config: SerializeAsAny[AgentConfig] | None = None
    correlation_id: str | None = None
    approval: AgentFlowApproval | None = None
    max_steps: int = Field(default=10, ge=1, le=100)


class AgentVerificationOverridePayload(VerificationOverrideCommand):
    expected_version: int = Field(ge=1)


class AgentFlowHeartbeatPayload(BaseModel):
    expected_version: int = Field(ge=1)
    lease_id: UUID


class AgentFlowRecoveryPayload(BaseModel):
    expected_version: int = Field(ge=1)
    recovered_by: str = Field(min_length=1, max_length=160)
    request: AgentExecutionRequestPayload
    config: SerializeAsAny[AgentConfig] | None = None
    max_steps: int = Field(default=10, ge=1, le=100)


@router.post("/execute", response_model=AgentExecutionResponse)
async def execute_agent(
    payload: AgentExecutePayload,
    db: AsyncSession = Depends(get_db),
) -> AgentExecutionResponse:
    config = payload.config or _default_config_for(payload.request.agent_type)
    if config.agent_type != payload.request.agent_type:
        raise HTTPException(
            status_code=422,
            detail="config.agent_type must match request.agent_type",
        )

    service = create_agent_platform_service_for_db(db)
    orchestration_result = await service.execute(
        _build_execution_request(
            request=payload.request,
            config=config,
            workflow_id=payload.workflow_id,
            correlation_id=payload.correlation_id,
        )
    )
    return AgentExecutionResponse(
        persisted_result_id=orchestration_result.persisted.result_id,
        result=orchestration_result.result,
        route=orchestration_result.route,
    )


@router.post("/flows", response_model=PersistedAgentFlow)
async def start_agent_flow(
    payload: AgentFlowStartPayload,
    db: AsyncSession = Depends(get_db),
) -> PersistedAgentFlow:
    config = payload.config or _default_config_for(payload.request.agent_type)
    _validate_config_type(payload.request.agent_type, config)
    service = create_agent_platform_service_for_db(db)
    try:
        return await service.start_flow(
            _build_execution_request(
                request=payload.request,
                config=config,
                workflow_id=payload.workflow_id,
                correlation_id=payload.correlation_id,
            ),
            max_steps=payload.max_steps,
        )
    except Exception as exc:
        raise _flow_http_exception(exc) from exc


@router.post(
    "/flows/async",
    response_model=PersistedAgentFlow,
    status_code=202,
)
async def enqueue_agent_flow(
    payload: AgentFlowStartPayload,
    db: AsyncSession = Depends(get_db),
) -> PersistedAgentFlow:
    config = payload.config or _default_config_for(payload.request.agent_type)
    _validate_config_type(payload.request.agent_type, config)
    service = create_agent_platform_service_for_db(db)
    try:
        return await service.enqueue_flow(
            _build_execution_request(
                request=payload.request,
                config=config,
                workflow_id=payload.workflow_id,
                correlation_id=payload.correlation_id,
            ),
            max_steps=payload.max_steps,
        )
    except Exception as exc:
        raise _flow_http_exception(exc) from exc


@router.get("/flows/by-workflow", response_model=PersistedAgentFlow)
async def get_agent_flow_by_workflow(
    project_id: str,
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
) -> PersistedAgentFlow:
    service = create_agent_platform_service_for_db(db)
    try:
        return await service.get_flow_by_workflow(
            project_id=project_id,
            workflow_id=workflow_id,
        )
    except Exception as exc:
        raise _flow_http_exception(exc) from exc


@router.get("/flows/{flow_id}", response_model=PersistedAgentFlow)
async def get_agent_flow(
    flow_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> PersistedAgentFlow:
    service = create_agent_platform_service_for_db(db)
    try:
        return await service.get_flow(flow_id)
    except Exception as exc:
        raise _flow_http_exception(exc) from exc


@router.post(
    "/flows/{flow_id}/verification-override",
    response_model=PersistedAgentFlow,
)
async def override_agent_verification(
    flow_id: UUID,
    payload: AgentVerificationOverridePayload,
    db: AsyncSession = Depends(get_db),
) -> PersistedAgentFlow:
    service = create_agent_platform_service_for_db(db)
    try:
        return await service.override_verification_flow(
            flow_id=flow_id,
            expected_version=payload.expected_version,
            command=VerificationOverrideCommand.model_validate(
                payload.model_dump(exclude={"expected_version"})
            ),
        )
    except Exception as exc:
        raise _flow_http_exception(exc) from exc


@router.post("/flows/{flow_id}/heartbeat", response_model=PersistedAgentFlow)
async def heartbeat_agent_flow(
    flow_id: UUID,
    payload: AgentFlowHeartbeatPayload,
    db: AsyncSession = Depends(get_db),
) -> PersistedAgentFlow:
    service = create_agent_platform_service_for_db(db)
    try:
        return await service.heartbeat_flow(
            flow_id=flow_id,
            lease_id=payload.lease_id,
            expected_version=payload.expected_version,
        )
    except Exception as exc:
        raise _flow_http_exception(exc) from exc


@router.post("/flows/{flow_id}/recover", response_model=PersistedAgentFlow)
async def recover_agent_flow(
    flow_id: UUID,
    payload: AgentFlowRecoveryPayload,
    db: AsyncSession = Depends(get_db),
) -> PersistedAgentFlow:
    service = create_agent_platform_service_for_db(db)
    try:
        current = await service.get_flow(flow_id)
        persisted_config = (
            current.pending_execution_payload.get("config")
            if current.pending_execution_payload is not None
            else None
        )
        if payload.config is None and not isinstance(persisted_config, dict):
            raise AgentValidationError("Running flow has no persisted agent configuration")
        config = payload.config or AgentConfig.model_validate(persisted_config)
        _validate_config_type(payload.request.agent_type, config)
        execution = _build_execution_request(
            request=payload.request,
            config=config,
            workflow_id=current.workflow_id,
            correlation_id=current.correlation_id,
        )
        return await service.recover_flow(
            flow_id=flow_id,
            expected_version=payload.expected_version,
            request=execution,
            recovered_by=payload.recovered_by,
            max_steps=payload.max_steps,
        )
    except Exception as exc:
        raise _flow_http_exception(exc) from exc


@router.post("/flows/{flow_id}/resume", response_model=PersistedAgentFlow)
async def resume_agent_flow(
    flow_id: UUID,
    payload: AgentFlowResumePayload,
    db: AsyncSession = Depends(get_db),
) -> PersistedAgentFlow:
    service = create_agent_platform_service_for_db(db)
    try:
        current = await service.get_flow(flow_id)
        execution = None
        if payload.request is not None:
            config = payload.config or _default_config_for(payload.request.agent_type)
            _validate_config_type(payload.request.agent_type, config)
            execution = _build_execution_request(
                request=payload.request,
                config=config,
                workflow_id=current.workflow_id,
                correlation_id=payload.correlation_id or current.correlation_id,
            )
        return await service.resume_flow(
            flow_id=flow_id,
            expected_version=payload.expected_version,
            request=execution,
            approval=payload.approval,
            max_steps=payload.max_steps,
        )
    except Exception as exc:
        raise _flow_http_exception(exc) from exc


def _default_config_for(agent_type: str) -> AgentConfig:
    config = load_agent_platform_config().agents.get(agent_type)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent type: {agent_type}")
    return config


def _validate_config_type(agent_type: str, config: AgentConfig) -> None:
    if config.agent_type != agent_type:
        raise HTTPException(
            status_code=422,
            detail="config.agent_type must match request.agent_type",
        )


def _build_execution_request(
    *,
    request: AgentExecutionRequestPayload,
    config: AgentConfig,
    workflow_id: str | None,
    correlation_id: str | None,
) -> AgentExecutionRequest:
    execution_kwargs = {
        "agent_type": request.agent_type,
        "request": request,
        "config": config,
    }
    if workflow_id is not None:
        execution_kwargs["workflow_id"] = workflow_id
    if correlation_id is not None:
        execution_kwargs["correlation_id"] = correlation_id
    return AgentExecutionRequest.model_validate(execution_kwargs)


def _flow_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, AgentFlowNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AgentFlowVersionConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AgentFlowLeaseConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AgentFlowPersistenceError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AgentValidationError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, HTTPException):
        return exc
    return HTTPException(status_code=500, detail=str(exc))
