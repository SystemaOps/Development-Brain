from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from typing import Sequence

from agent_core.ports.command_runner import CommandResult, CommandRunnerPort


class SafeSubprocessCommandRunner(CommandRunnerPort):
    def __init__(self, *, secrets: Sequence[str] = ()) -> None:
        self.secrets = tuple(secret for secret in secrets if len(secret) >= 4)

    async def run(
        self,
        *,
        command: Sequence[str],
        cwd: str,
        timeout_seconds: int,
        output_limit_bytes: int,
    ) -> CommandResult:
        args = _validate_command(command)
        working_directory = Path(cwd).resolve(strict=True)
        if not working_directory.is_dir():
            raise ValueError(f"Command cwd is not a directory: {working_directory}")

        started = time.monotonic()
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                list(args),
                cwd=str(working_directory),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                shell=False,
            )
            return CommandResult(
                command=tuple(_redact_text(arg, self.secrets) for arg in args),
                exit_code=completed.returncode,
                stdout=_truncate(_redact_text(completed.stdout or "", self.secrets), output_limit_bytes),
                stderr=_truncate(_redact_text(completed.stderr or "", self.secrets), output_limit_bytes),
                duration_seconds=time.monotonic() - started,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _coerce_output(exc.stdout)
            stderr = _coerce_output(exc.stderr)
            return CommandResult(
                command=tuple(_redact_text(arg, self.secrets) for arg in args),
                exit_code=-1,
                stdout=_truncate(_redact_text(stdout, self.secrets), output_limit_bytes),
                stderr=_truncate(_redact_text(stderr or f"Command timed out after {timeout_seconds} seconds", self.secrets), output_limit_bytes),
                duration_seconds=time.monotonic() - started,
                timed_out=True,
            )
        except OSError as exc:
            return CommandResult(
                command=tuple(_redact_text(arg, self.secrets) for arg in args),
                exit_code=-1,
                stdout="",
                stderr=_truncate(_redact_text(str(exc), self.secrets), output_limit_bytes),
                duration_seconds=time.monotonic() - started,
                timed_out=False,
            )


def _validate_command(command: Sequence[str]) -> tuple[str, ...]:
    if isinstance(command, str):
        raise ValueError("commands must be argument arrays, not shell strings")
    args = tuple(str(part) for part in command)
    if not args:
        raise ValueError("command cannot be empty")
    if any(not part.strip() for part in args):
        raise ValueError("command arguments cannot be blank")
    return args


def _redact_text(value: str, secrets: Sequence[str]) -> str:
    redacted = value
    for secret in secrets:
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _truncate(value: str, limit_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit_bytes:
        return value
    truncated = encoded[:limit_bytes].decode("utf-8", errors="ignore")
    omitted = len(encoded) - len(truncated.encode("utf-8"))
    return f"{truncated}\n...[truncated {omitted} bytes]"


def _coerce_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
