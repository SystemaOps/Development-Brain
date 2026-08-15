"""Deterministic command runner (Task 13.2).

Runs project-configured checks (unit/integration tests, lint, format, type
checks, build) and captures stdout/stderr/exit code as evidence.  A
deterministic fake variant is provided for tests; the real runner uses
``asyncio.create_subprocess_shell``.
"""

from __future__ import annotations

import asyncio

from brain.ports.verification import CommandRunner


class DeterministicCommandRunner(CommandRunner):
    """Runs commands and captures output as evidence."""

    async def run(
        self,
        command: str,
        *,
        workspace_path: str | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, object]:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=workspace_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "command": command,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"command timed out after {timeout_seconds}s",
            }
        return {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }


class FakeCommandRunner(CommandRunner):
    """Deterministic command runner for tests."""

    def __init__(self, *, default_exit_code: int = 0) -> None:
        self._default_exit_code = default_exit_code
        self.runs: list[dict[str, object]] = []
        self.results: dict[str, dict[str, object]] = {}

    async def run(
        self,
        command: str,
        *,
        workspace_path: str | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, object]:
        result = self.results.get(command)
        if result is None:
            result = {
                "command": command,
                "exit_code": self._default_exit_code,
                "stdout": f"ran: {command}",
                "stderr": "",
            }
        self.runs.append({"command": command, "workspace_path": workspace_path})
        return dict(result)


__all__ = ["DeterministicCommandRunner", "FakeCommandRunner"]
