"""Command failure repository contract (Phase 25)."""

from __future__ import annotations

import uuid

import pytest

from brain.domain.command_failure import (
    CommandFailure,
    CommandFailureCategory,
)
from brain.ports.command_failure import CommandFailureRepository


class CommandFailureRepositoryContract:
    @pytest.fixture
    def command_failures(self) -> CommandFailureRepository:
        raise NotImplementedError

    def test_adapter_conforms_to_port(self, command_failures: CommandFailureRepository) -> None:
        assert isinstance(command_failures, CommandFailureRepository)

    async def test_save_and_list_by_command(
        self, command_failures: CommandFailureRepository
    ) -> None:
        command_id = uuid.uuid4()
        failure = CommandFailure(
            command_id=command_id,
            command_type="run_work_item",
            attempt=2,
            category=CommandFailureCategory.EXECUTION_FAILURE,
            message="boom",
            correlation_id=uuid.uuid4(),
            retry_eligible=True,
        )
        await command_failures.save(failure)
        listed = await command_failures.list_by_command(command_id)
        assert [f.id for f in listed] == [failure.id]
        assert listed[0].category == CommandFailureCategory.EXECUTION_FAILURE
        assert listed[0].retry_eligible is True

    async def test_list_recent(self, command_failures: CommandFailureRepository) -> None:
        failure = CommandFailure(
            command_id=uuid.uuid4(),
            command_type="analyze_project",
            category=CommandFailureCategory.INTERNAL,
            message="x",
        )
        await command_failures.save(failure)
        recent = await command_failures.list_recent(limit=10)
        assert any(f.id == failure.id for f in recent)
