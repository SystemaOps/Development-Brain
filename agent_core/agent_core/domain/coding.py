from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.enums import CodingAttemptStatus
from agent_core.domain.evidence import EvidenceRef


class FileChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    relative_path: str
    content: str
    change_type: Literal["upsert"] = "upsert"


class QualityCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    command: tuple[str, ...]
    timeout_seconds: int = Field(default=600, ge=1, le=3600)
    output_limit_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)

    @field_validator("command", mode="before")
    @classmethod
    def command_must_be_argument_sequence(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            raise ValueError("commands must be argument arrays, not shell strings")
        try:
            command = tuple(str(item) for item in value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError("commands must be argument arrays") from exc
        if not command:
            raise ValueError("command cannot be empty")
        if any(not item.strip() for item in command):
            raise ValueError("command arguments cannot be blank")
        return command


class CommandExecutionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


class RollbackPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    strategy: str
    reason: str | None = None
    base_commit_sha: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    reverse_diff: str | None = None


class CodingAttemptRequest(BaseModel):
    task_key: str
    repository_key: str
    file_changes: list[FileChange] = Field(default_factory=list)
    quality_commands: list[QualityCommand] = Field(default_factory=list)

    @model_validator(mode="after")
    def at_least_one_change_or_command(self) -> "CodingAttemptRequest":
        if not self.file_changes and not self.quality_commands:
            raise ValueError("coding attempts require at least one file change or quality command")
        return self


class CodingAttemptResult(BaseModel):
    task_key: str
    repository_key: str
    attempt_number: int
    status: CodingAttemptStatus
    base_commit_sha: str | None = None
    branch: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    command_results: list[CommandExecutionRecord] = Field(default_factory=list)
    final_diff: str = ""
    rollback_plan: RollbackPlan
    errors: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status == CodingAttemptStatus.SUCCEEDED
