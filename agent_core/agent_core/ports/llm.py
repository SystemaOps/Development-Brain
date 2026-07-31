from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class StructuredGenerationPort(Protocol):
    async def generate(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        temperature: float = 0.1,
    ) -> T:
        ...
