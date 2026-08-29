"""Helpers to translate between canonical domain models and row dictionaries.

Domain value objects serialize through Pydantic (``model_dump(mode="json")``)
into JSON-safe structures stored in JSONB columns; reading them back uses
``Model.model_validate`` which accepts the same JSON-safe structure, so the
canonical model never depends on the persistence layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel


def dump_model(model: BaseModel) -> dict[str, Any]:
    """Serialize a single value object to a JSON-safe mapping."""
    return model.model_dump(mode="json")


def dump_models(models: Sequence[BaseModel]) -> list[dict[str, Any]]:
    """Serialize value objects to JSON-safe mappings."""
    return [model.model_dump(mode="json") for model in models]


def dump_uuids(uuids: list[Any]) -> list[str]:
    """Serialize a list of UUID values to strings for JSONB storage."""
    return [str(value) for value in uuids]
