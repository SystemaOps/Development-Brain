from __future__ import annotations

import json
from typing import TypeVar, Type

import httpx
from pydantic import BaseModel

from agent_core.config import settings

T = TypeVar("T", bound=BaseModel)


class StructuredLLM:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            base_url=settings.llm_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            timeout=180,
        )

    async def generate(self, *, system: str, user: str, output_model: Type[T], temperature: float = 0.1) -> T:
        schema = output_model.model_json_schema()
        payload = {
            "model": settings.llm_model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"{user}\n\nReturn only JSON satisfying this schema:\n{json.dumps(schema)}"},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": output_model.__name__, "schema": schema, "strict": True},
            },
        }
        response = await self.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        return output_model.model_validate_json(response.json()["choices"][0]["message"]["content"])

    async def close(self) -> None:
        await self.client.aclose()
