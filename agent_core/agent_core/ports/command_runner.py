from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


class CommandRunnerPort(Protocol):
    async def run(
        self,
        *,
        command: Sequence[str],
        cwd: str,
        timeout_seconds: int,
        output_limit_bytes: int,
    ) -> CommandResult:
        ...
