"""Impact analysis service (Task 7.11).

Given target symbols, task concepts and a repository revision, answer: where
is it defined, what does it call, what calls it, which files are related,
which tests are related, and how risky the change is.  Pure domain+ports
implementation over the parsed code graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from brain.domain.code_intelligence import (
    CodeRelation,
    CodeRelationType,
    Symbol,
    is_test_path,
)
from brain.domain.identity import RepositoryId
from brain.ports.code_intelligence import CodeGraphRepository


@dataclass
class ImpactAnalysis:
    repository_id: RepositoryId
    revision: str
    primary_symbols: list[Symbol] = field(default_factory=list)
    direct_dependents: list[CodeRelation] = field(default_factory=list)
    reverse_dependencies: list[CodeRelation] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    related_tests: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    configuration: list[str] = field(default_factory=list)
    risk_score: float = 0.0


class ImpactAnalysisService:
    """Compute the impact neighborhood for symbols at one revision."""

    def __init__(self, *, repository: CodeGraphRepository) -> None:
        self._repository = repository

    async def analyze(
        self,
        repository_id: RepositoryId,
        revision: str,
        target_symbols: list[str],
        task_concepts: list[str] | None = None,
    ) -> ImpactAnalysis:
        del task_concepts
        symbols = await self._repository.list_symbols(repository_id, revision)
        relations = await self._repository.list_relations(repository_id, revision)

        primary = self._select_primary(symbols, target_symbols)
        primary_keys = {symbol.identity_key for symbol in primary}

        dependents = [
            rel
            for rel in relations
            if rel.relation_type == CodeRelationType.CALLS
            and rel.target_identity.key in primary_keys
        ]
        reverse = [
            rel
            for rel in relations
            if rel.relation_type == CodeRelationType.CALLS
            and rel.source_identity.key in primary_keys
        ]

        file_candidates: set[str] = set()
        for rel in (*dependents, *reverse):
            if rel.target_path:
                file_candidates.add(rel.target_path)
            if rel.source_path:
                file_candidates.add(rel.source_path)
        file_candidates.update(symbol.path for symbol in primary)
        related_files = sorted(file_candidates)
        related_tests = sorted(
            {
                rel.target_path
                for rel in relations
                if rel.relation_type == CodeRelationType.TESTS and rel.target_path in related_files
            }
        )
        for symbol in symbols:
            if is_test_path(symbol.path):
                related_tests.append(symbol.path)

        interfaces = sorted(
            {
                rel.target_identity.qualified_name
                for rel in reverse
                if rel.relation_type == CodeRelationType.CALLS
            }
        )
        configuration = [
            path
            for path in related_files
            if path.endswith((".yaml", ".yml", ".toml", ".ini", ".cfg", ".env"))
        ]

        risk = self._risk_score(primary, reverse, related_files)
        return ImpactAnalysis(
            repository_id=repository_id,
            revision=revision,
            primary_symbols=primary,
            direct_dependents=dependents,
            reverse_dependencies=reverse,
            related_files=related_files,
            related_tests=sorted(set(related_tests)),
            interfaces=interfaces,
            configuration=configuration,
            risk_score=risk,
        )

    @staticmethod
    def _select_primary(symbols: list[Symbol], target_symbols: list[str]) -> list[Symbol]:
        found: list[Symbol] = []
        for target in target_symbols:
            candidates = [symbol for symbol in symbols if symbol.qualified_name == target]
            if candidates:
                found.extend(candidates)
                continue
            # Partial match on the trailing qualified-name segment.
            for symbol in symbols:
                if symbol.qualified_name.rsplit(".", 1)[-1] == target:
                    found.append(symbol)
        # De-duplicate by identity key.
        seen: set[str] = set()
        unique: list[Symbol] = []
        for symbol in found:
            if symbol.identity_key not in seen:
                seen.add(symbol.identity_key)
                unique.append(symbol)
        return unique

    @staticmethod
    def _risk_score(
        primary: list[Symbol], reverse: list[CodeRelation], related_files: list[str]
    ) -> float:
        """Deterministic heuristic risk score in ``[0, 1]``."""
        score = 0.0
        if not primary:
            return 0.0
        # More callers and more related files increase the blast radius.
        score += min(0.4, len(reverse) * 0.1)
        score += min(0.3, len(related_files) * 0.05)
        # Core/service modules are riskier than leaf utilities.
        for symbol in primary:
            module = symbol.identity.module.lower()
            if any(token in module for token in ("core", "service", "domain", "model")):
                score += 0.15
                break
        return round(min(1.0, score), 2)


__all__ = ["ImpactAnalysis", "ImpactAnalysisService"]
