from __future__ import annotations

from agent_core.ports.command_runner import CommandRunnerPort


class CommandRunner(CommandRunnerPort):
    """Platform-facing command runner interface for tool and test execution."""


__all__ = ["CommandRunner"]
