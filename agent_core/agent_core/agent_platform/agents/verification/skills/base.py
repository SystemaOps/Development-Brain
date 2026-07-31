from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel


InputT = TypeVar("InputT", bound=BaseModel, contravariant=True)
OutputT = TypeVar("OutputT", bound=BaseModel, covariant=True)


class VerificationSkill(Protocol[InputT, OutputT]):
    name: str
    required_dependencies: tuple[str, ...]

    async def run(self, input_data: InputT) -> OutputT: ...


class VerificationSkillError(RuntimeError):
    def __init__(self, *, skill_name: str, code: str, message: str) -> None:
        super().__init__(message)
        self.skill_name = skill_name
        self.code = code
