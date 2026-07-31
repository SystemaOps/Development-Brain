from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


SkillStatus = Literal["implemented", "planned"]


class SkillManifest(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str
    input_schema: str | None = None
    output_schema: str | None = None
    side_effects: bool = False
    required_tools: list[str] = Field(default_factory=list)
    status: SkillStatus = "implemented"

    @model_validator(mode="after")
    def planned_skills_cannot_have_side_effects(self) -> "SkillManifest":
        if self.status == "planned" and self.side_effects:
            raise ValueError("planned skills cannot declare side effects")
        return self


class SkillManifestSet(BaseModel):
    manifests: list[SkillManifest]


def load_skill_manifests(directory: Path) -> dict[str, SkillManifest]:
    manifests: dict[str, SkillManifest] = {}
    for path in sorted(directory.glob("*.json")):
        manifest = SkillManifest.model_validate_json(path.read_text(encoding="utf-8"))
        if manifest.name in manifests:
            raise ValueError(f"Duplicate skill manifest: {manifest.name}")
        manifests[manifest.name] = manifest
    return manifests


def load_builtin_skill_manifests() -> dict[str, SkillManifest]:
    return load_skill_manifests(Path(__file__).with_name("manifests"))


def dump_manifest(manifest: SkillManifest) -> str:
    return json.dumps(manifest.model_dump(), indent=2, sort_keys=True)
