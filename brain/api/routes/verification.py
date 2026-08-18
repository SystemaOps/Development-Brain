"""Verification routes (Phase 23)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from brain.api.dependencies import get_container
from brain.api.errors import BrainAPIError
from brain.api.schemas import VerificationRead, VerificationRequest
from brain.bootstrap.container import BrainContainer
from brain.domain.identity import (
    ExecutionId,
    RepositoryId,
    VerificationId,
    WorkItemId,
)
from brain.domain.verification_plan import VerificationRun
from brain.ports.verification import VerificationRunRepository

router = APIRouter()


def _to_read(run: VerificationRun) -> VerificationRead:
    return VerificationRead(
        id=run.id,
        execution_id=run.execution_id,
        verdict=run.verdict.value,
        issues=list(run.issues),
        feedback=list(run.feedback),
        pr_allowed=bool(run.pr_allowed),
    )


@router.post("/api/v1/executions/{execution_id}/verify", response_model=VerificationRead)
async def verify_execution(
    execution_id: uuid.UUID, payload: VerificationRequest, request: Request
) -> VerificationRead:
    container: BrainContainer = get_container(request)
    result = await container.verification.verify(
        execution_id=ExecutionId(execution_id),
        work_item_id=WorkItemId(payload.work_item_id),
        acceptance_criteria=payload.acceptance_criteria,
        changed_files=payload.changed_files,
        repository_id=RepositoryId(payload.repository_id) if payload.repository_id else None,
        revision=payload.revision,
    )
    return _to_read(result.run)


@router.get("/api/v1/verifications/{verification_id}", response_model=VerificationRead)
async def get_verification(verification_id: uuid.UUID, request: Request) -> VerificationRead:
    container: BrainContainer = get_container(request)
    results: VerificationRunRepository = container.repositories.verification_runs
    run = await results.get_run(VerificationId(verification_id))
    if run is None:
        raise BrainAPIError("not_found", "verification not found", status_code=404)
    return _to_read(run)


@router.post("/api/v1/verifications/{verification_id}/rerun", status_code=202)
async def rerun_verification(verification_id: uuid.UUID, request: Request) -> dict[str, str]:
    del verification_id, request
    return {"status": "ACCEPTED"}


@router.get("/api/v1/verifications/{verification_id}/evidence")
async def verification_evidence(verification_id: uuid.UUID, request: Request) -> dict[str, object]:
    del verification_id, request
    return {"evidence": []}


@router.get("/api/v1/verifications/{verification_id}/failures")
async def verification_failures(verification_id: uuid.UUID, request: Request) -> dict[str, object]:
    container: BrainContainer = get_container(request)
    results: VerificationRunRepository = container.repositories.verification_runs
    run = await results.get_run(VerificationId(verification_id))
    if run is None:
        raise BrainAPIError("not_found", "verification not found", status_code=404)
    return {"verification_id": str(verification_id), "failures": list(run.issues)}
