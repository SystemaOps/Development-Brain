from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from agent_core.agent_platform.agents.verification.contracts import (
    VerificationVerdict,
)
from agent_core.agent_platform.config.models import AgentConfig


class VerificationAgentConfig(AgentConfig):
    agent_type: str = "verification"
    checkpoint_namespace: str = "verification"
    approval_required: bool = False
    independent_workspace: bool = True
    require_diff_for_pass: bool = True
    require_test_command_for_pass: bool = False
    require_test_evidence_for_source_changes: bool = False
    warning_terms: list[str] = Field(default_factory=lambda: ["todo", "fixme", "temporary", "hack"])
    sensitive_path_patterns: list[str] = Field(
        default_factory=lambda: [
            "auth",
            "security",
            "permission",
            "migration",
            "config",
            ".env",
            "docker-compose",
        ]
    )
    large_change_line_threshold: int = Field(default=500, ge=1)
    large_change_file_threshold: int = Field(default=20, ge=1)
    warn_on_sensitive_changes: bool = False
    warn_on_missing_rollback: bool = False
    security_review_enabled: bool = True
    openproject_projection_enabled: bool = True
    openproject_verified_status_name: str = "Verified"
    openproject_changes_required_status_name: str = "Changes required"
    openproject_blocked_status_name: str = "Blocked"
    openproject_override_status_name: str = "Done"
    human_override_enabled: bool = False
    human_override_allowed_verdicts: list[VerificationVerdict] = Field(
        default_factory=lambda: [VerificationVerdict.CHANGES_REQUESTED]
    )

    @field_validator("human_override_allowed_verdicts")
    @classmethod
    def override_verdicts_must_require_intervention(
        cls,
        value: list[VerificationVerdict],
    ) -> list[VerificationVerdict]:
        invalid = set(value) - {
            VerificationVerdict.CHANGES_REQUESTED,
            VerificationVerdict.BLOCKED,
        }
        if invalid:
            raise ValueError(
                "human overrides can only target changes_requested or blocked verdicts"
            )
        if len(value) != len(set(value)):
            raise ValueError("human_override_allowed_verdicts cannot contain duplicates")
        return value

    @field_validator(
        "openproject_verified_status_name",
        "openproject_changes_required_status_name",
        "openproject_blocked_status_name",
        "openproject_override_status_name",
    )
    @classmethod
    def openproject_status_names_cannot_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("OpenProject status names cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def enabled_override_requires_an_eligible_verdict(self) -> "VerificationAgentConfig":
        if self.human_override_enabled and not self.human_override_allowed_verdicts:
            raise ValueError(
                "human_override_allowed_verdicts cannot be empty when override is enabled"
            )
        return self

    def allows_human_override(self, verdict: VerificationVerdict) -> bool:
        return self.human_override_enabled and verdict in self.human_override_allowed_verdicts
