"""Pi executor adapter (Task 12.6).

Talks to a Pi process over a JSONL/RPC protocol: the Python brain writes one
JSON request per line and reads one JSON result per line.  The transport is
pluggable so tests can inject a fake Pi process; the core domain never sees Pi
session models -- only the canonical :class:`ExecutionRequest` /
:class:`ExecutionResult`.

Session history lives in the adapter only; canonical project knowledge never
depends on Pi session files (Task 12.10).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from brain.domain.executions import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
)
from brain.domain.identity import ExecutionId
from brain.ports.executor import ExecutorPort


class PiTransport(Protocol):
    """Sends a request dict to Pi and returns the raw response dict."""

    async def round_trip(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class PiExecutor(ExecutorPort):
    """Executes a WorkItem through a Pi process via JSONL/RPC."""

    def __init__(self, transport: PiTransport | None = None) -> None:
        self._transport = transport or _SubprocessPiTransport(command=[])

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        payload = _request_to_payload(request)
        try:
            response = await self._transport.round_trip(payload)
        except Exception as exc:  # noqa: BLE001 - failure isolation (Task 37.6)
            return ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.FAILED,
                blockers=[f"pi transport failure: {exc}"],
                observations=["Pi execution failed; worker process stays alive"],
            )
        return _result_from_payload(request.execution_id, response)


class PiHTTPTransport:
    """HTTP transport to a Pi executor service (Task 37.2)."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        timeout_seconds: int = 120,
    ) -> None:

        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    async def round_trip(self, payload: dict[str, Any]) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            f"{self._base_url}/execute",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
                return dict(json.loads(body))
        except urllib.error.HTTPError as exc:
            raise PiExecutionError(
                f"pi /execute -> {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise PiExecutionError(f"pi unreachable: {exc}") from exc


def build_pi_transport(
    *,
    pi_url: str = "",
    pi_api_key: str = "",
) -> PiTransport:
    """Pick the Pi transport: HTTP when a URL is configured, else subprocess."""
    if pi_url:
        return PiHTTPTransport(base_url=pi_url, api_key=pi_api_key)
    return _SubprocessPiTransport(command=[])


class PiExecutionError(RuntimeError):
    """Raised when the Pi service cannot complete a request."""


class _SubprocessPiTransport:
    """Spawns a Pi process and exchanges JSON lines over its stdio.

    Used when a Pi binary is configured.  With an empty ``command`` this
    transport returns a placeholder result so the adapter is testable without
    Pi installed.
    """

    def __init__(self, command: list[str]) -> None:
        self._command = command

    async def round_trip(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._command:
            return {
                "status": "completed",
                "modified_files": [],
                "observations": ["Pi transport not configured; placeholder result"],
            }
        # JSONL subprocess protocol: write request, read response line.
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        assert proc.stdout is not None
        raw = await proc.stdout.readline()
        await proc.wait()
        data = json.loads(raw.decode("utf-8"))
        return dict(data)


def _request_to_payload(request: ExecutionRequest) -> dict[str, Any]:
    return {
        "execution_id": str(request.execution_id),
        "workflow_id": str(request.workflow_id),
        "work_item_id": str(request.work_item_id),
        "repository_ref": request.repository_ref,
        "base_revision": request.base_revision,
        "base_branch": request.base_branch,
        "working_branch": request.working_branch,
        "worktree_path": request.worktree_path,
        "workspace_path": request.workspace_path,
        "context_capsule_id": str(request.context_capsule_id)
        if request.context_capsule_id
        else None,
        "permissions": request.permissions.model_dump(mode="json"),
        "tools": [
            "brain_get_task",
            "brain_get_symbol_context",
            "brain_find_related_files",
            "brain_find_related_tests",
            "brain_get_requirement",
            "brain_get_architecture_constraints",
            "brain_search_project_knowledge",
            "brain_request_more_context",
        ],
    }


def _result_from_payload(execution_id: ExecutionId, response: dict[str, Any]) -> ExecutionResult:
    status = _status_from(response.get("status", "completed"))
    return ExecutionResult(
        execution_id=execution_id,
        status=status,
        modified_files=_list(response.get("modified_files")),
        created_files=_list(response.get("created_files")),
        deleted_files=_list(response.get("deleted_files")),
        commands_executed=_list(response.get("commands_executed")),
        tests_executed=_list(response.get("tests_executed")),
        diff=response.get("diff"),
        observations=_list(response.get("observations")),
        blockers=_list(response.get("blockers")),
    )


def _list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _status_from(value: str) -> ExecutionStatus:
    lowered = value.lower()
    try:
        return ExecutionStatus(lowered)
    except ValueError:
        return ExecutionStatus.COMPLETED


__all__ = ["PiExecutor", "PiExecutionError", "PiHTTPTransport", "PiTransport", "build_pi_transport"]
