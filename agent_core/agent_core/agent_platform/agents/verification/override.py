from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_core.agent_platform.agents.verification.config import (
    VerificationAgentConfig,
)
from agent_core.agent_platform.agents.verification.state import (
    VerificationAgentResult,
)


class VerificationOverrideCommand(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    actor: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=4000)
    override_reference: str = Field(min_length=1, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationOverrideType(StrEnum):
    COMPLETION = "verification_completion"


class VerificationOverrideAssessment(BaseModel):
    original_verdict: str
    finding_codes: list[str] = Field(default_factory=list)
    acceptance_criterion_keys: list[str] = Field(default_factory=list)


class VerificationOverridePolicyError(ValueError):
    pass


def assess_verification_override(
    *,
    config: VerificationAgentConfig,
    result: VerificationAgentResult,
) -> VerificationOverrideAssessment:
    if not config.human_override_enabled:
        raise VerificationOverridePolicyError(
            "Human override is disabled for this Verification Agent execution"
        )
    if not config.allows_human_override(result.verdict):
        raise VerificationOverridePolicyError(
            f"Verification verdict is not eligible for override: {result.verdict.value}"
        )
    if not result.human_override_eligible:
        raise VerificationOverridePolicyError(
            "Verification result was not emitted as eligible for human override"
        )

    return VerificationOverrideAssessment(
        original_verdict=result.verdict.value,
        finding_codes=sorted({finding.code for finding in result.findings}),
        acceptance_criterion_keys=sorted(
            {
                finding.acceptance_criterion_key
                for finding in result.findings
                if finding.acceptance_criterion_key is not None
            }
        ),
    )


__all__ = [
    "VerificationOverrideAssessment",
    "VerificationOverrideCommand",
    "VerificationOverridePolicyError",
    "VerificationOverrideType",
    "assess_verification_override",
]
