from __future__ import annotations

from collections.abc import Mapping

from agent_core.skills.base import BaseSkill
from agent_core.skills.manifest import SkillManifest


class SkillRegistry:
    def __init__(self, manifests: Mapping[str, SkillManifest] | None = None) -> None:
        self._skills: dict[str, BaseSkill] = {}
        self._manifests: dict[str, SkillManifest] = dict(manifests or {})

    def register(self, skill: BaseSkill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"Skill already registered: {skill.name}")
        self._validate_skill_manifest(skill)
        self._skills[skill.name] = skill

    def get(self, name: str) -> BaseSkill:
        if name not in self._skills:
            if name in self._manifests:
                raise KeyError(f"Skill is declared but not registered as runnable: {name}")
            raise KeyError(f"Unknown skill: {name}")
        return self._skills[name]

    def all(self) -> list[BaseSkill]:
        return list(self._skills.values())

    def names(self) -> list[str]:
        return list(self._skills.keys())

    def register_manifest(self, manifest: SkillManifest) -> None:
        if manifest.name in self._manifests:
            raise ValueError(f"Skill manifest already registered: {manifest.name}")
        self._manifests[manifest.name] = manifest

    def manifest(self, name: str) -> SkillManifest:
        if name not in self._manifests:
            raise KeyError(f"Unknown skill manifest: {name}")
        return self._manifests[name]

    def manifests(self) -> list[SkillManifest]:
        return list(self._manifests.values())

    def manifest_names(self) -> list[str]:
        return sorted(self._manifests)

    def planned_names(self) -> list[str]:
        return sorted(
            manifest.name
            for manifest in self._manifests.values()
            if manifest.status == "planned"
        )

    def runnable_names(self) -> list[str]:
        return sorted(self._skills)

    def validate_required_manifests(self, required_names: list[str] | tuple[str, ...]) -> None:
        missing = sorted(set(required_names) - set(self._manifests))
        if missing:
            raise ValueError(f"Missing required skill manifests: {', '.join(missing)}")

    def _validate_skill_manifest(self, skill: BaseSkill) -> None:
        manifest = self._manifests.get(skill.name)
        if manifest is None:
            return

        if manifest.status != "implemented":
            raise ValueError(
                f"Skill {skill.name} cannot be registered because its manifest is {manifest.status}"
            )

        if manifest.side_effects != skill.side_effects:
            raise ValueError(
                f"Skill {skill.name} side-effect declaration does not match manifest"
            )

        if manifest.input_schema and _schema_name(skill.input_schema) != manifest.input_schema:
            raise ValueError(f"Skill {skill.name} input schema does not match manifest")

        if manifest.output_schema and _schema_name(skill.output_schema) != manifest.output_schema:
            raise ValueError(f"Skill {skill.name} output schema does not match manifest")


def _schema_name(schema: type | None) -> str | None:
    if schema is None:
        return None
    return f"{schema.__module__}.{schema.__qualname__}"
