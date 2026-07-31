from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from agent_core.domain.enums import ImplementationStatus
from agent_core.domain.evidence import EvidenceRef
from agent_core.skills.base import BaseSkill, SkillContext, SkillResult


class ImplementationStatusClassificationInput(BaseModel):
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    repository_inspection: dict[str, Any] | None = None
    repository_evidence: list[dict[str, Any]] = Field(default_factory=list)
    repository_symbols: list[dict[str, Any]] = Field(default_factory=list)
    min_complete_score: int = Field(default=4, ge=1, le=20)
    min_partial_score: int = Field(default=2, ge=1, le=20)


class RequirementImplementationClassification(BaseModel):
    requirement_key: str
    requirement_statement: str
    status: ImplementationStatus
    confidence: float
    rationale: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)


class ImplementationStatusClassificationOutput(BaseModel):
    classifications: list[RequirementImplementationClassification] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ImplementationStatusClassificationSkill(BaseSkill):
    name = "implementation_status_classification"
    description = "Classifies requirements against repository evidence."
    input_schema = ImplementationStatusClassificationInput
    output_schema = ImplementationStatusClassificationOutput
    side_effects = False

    def can_handle(self, intent: str, context: SkillContext) -> float:
        lowered = intent.lower()
        if any(word in lowered for word in ["implementation status", "classify", "complete", "missing", "partial"]):
            return 0.9
        if "implementation" in lowered:
            return 0.72
        return 0.28

    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict[str, Any],
    ) -> SkillResult:
        parsed = ImplementationStatusClassificationInput.model_validate(input_data or {})
        requirements = _normalize_requirements(parsed.requirements)
        evidence = _collect_evidence(parsed)
        warnings: list[str] = []
        if not requirements:
            warnings.append("No requirements were provided for implementation classification.")
        if not evidence:
            warnings.append("No repository evidence was provided; requirements are unverifiable.")

        classifications = [
            _classify_requirement(
                requirement,
                evidence=evidence,
                min_complete_score=parsed.min_complete_score,
                min_partial_score=parsed.min_partial_score,
            )
            for requirement in requirements
        ]
        summary: dict[str, int] = {status.value: 0 for status in ImplementationStatus}
        for classification in classifications:
            summary[classification.status.value] += 1

        output = ImplementationStatusClassificationOutput(
            classifications=classifications,
            summary=summary,
            warnings=warnings,
        )
        return SkillResult(
            skill_name=self.name,
            success=True,
            output=output.model_dump(mode="json"),
            source_refs=[
                ref.model_dump(mode="json")
                for classification in classifications
                for ref in classification.evidence
            ],
            errors=warnings,
        )


def _normalize_requirements(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    requirements: list[dict[str, str]] = []
    for index, item in enumerate(items, start=1):
        statement = item.get("statement") or item.get("text") or item.get("title")
        if not statement:
            continue
        key = item.get("key") or f"req.{index}"
        requirements.append({"key": str(key), "statement": str(statement)})
    return requirements


def _collect_evidence(parsed: ImplementationStatusClassificationInput) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    if parsed.repository_inspection:
        evidence.extend(parsed.repository_inspection.get("evidence") or [])
    evidence.extend(parsed.repository_evidence)
    for symbol in parsed.repository_symbols:
        text = " ".join(
            str(symbol.get(key) or "")
            for key in ["name", "kind", "relative_path"]
        )
        evidence.append(
            {
                "evidence_type": "code_symbol",
                "uri": f"repository://{symbol.get('repository_key', 'unknown')}/{symbol.get('relative_path', '')}#{symbol.get('symbol_key', '')}",
                "name": symbol.get("name"),
                "kind": symbol.get("kind"),
                "excerpt": text,
                "metadata": symbol.get("metadata") or {},
            }
        )
    return evidence


def _classify_requirement(
    requirement: dict[str, str],
    *,
    evidence: list[dict[str, Any]],
    min_complete_score: int,
    min_partial_score: int,
) -> RequirementImplementationClassification:
    terms = _terms(requirement["statement"])
    if not evidence:
        return RequirementImplementationClassification(
            requirement_key=requirement["key"],
            requirement_statement=requirement["statement"],
            status=ImplementationStatus.UNVERIFIABLE,
            confidence=0.0,
            rationale="No repository evidence was available.",
        )

    matches: list[tuple[int, dict[str, Any], list[str]]] = []
    for item in evidence:
        evidence_text = " ".join(
            str(item.get(key) or "")
            for key in ["name", "kind", "relative_path", "excerpt"]
        )
        matched = sorted(terms.intersection(_terms(evidence_text)))
        if matched:
            matches.append((len(matched), item, matched))

    if any(_contains_conflict_marker(item) for _, item, _ in matches):
        status = ImplementationStatus.CONFLICTING
        confidence = 0.7
        rationale = "Matching evidence contains conflict markers such as TODO, stub, or not implemented."
    elif not matches:
        status = ImplementationStatus.MISSING
        confidence = 0.75
        rationale = "No repository evidence matched requirement terms."
    else:
        best_score = max(score for score, _, _ in matches)
        has_test_evidence = any(_is_test_evidence(item) for _, item, _ in matches)
        if best_score >= min_complete_score and has_test_evidence:
            status = ImplementationStatus.COMPLETE
            confidence = 0.82
            rationale = "Requirement terms matched implementation and test evidence."
        elif best_score >= min_complete_score:
            status = ImplementationStatus.PARTIAL
            confidence = 0.68
            rationale = "Requirement terms matched implementation evidence, but no test evidence was found."
        elif best_score >= min_partial_score:
            status = ImplementationStatus.PARTIAL
            confidence = 0.55
            rationale = "Some requirement terms matched repository evidence."
        else:
            status = ImplementationStatus.MISSING
            confidence = 0.6
            rationale = "Repository evidence was present but did not meet the match threshold."

    selected = sorted(matches, key=lambda item: item[0], reverse=True)[:5]
    evidence_refs = [
        EvidenceRef(
            evidence_type=str(item.get("evidence_type") or "repository_evidence"),
            uri=str(item.get("uri") or "repository://unknown"),
            title=str(item.get("name") or item.get("title") or "Repository evidence"),
            excerpt=item.get("excerpt"),
            metadata=item.get("metadata") or {},
        )
        for _, item, _ in selected
    ]
    matched_terms = sorted({term for _, _, matched in selected for term in matched})
    return RequirementImplementationClassification(
        requirement_key=requirement["key"],
        requirement_statement=requirement["statement"],
        status=status,
        confidence=confidence,
        rationale=rationale,
        evidence=evidence_refs,
        matched_terms=matched_terms,
    )


_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "must",
    "shall",
    "should",
    "need",
    "needs",
    "required",
    "support",
    "allow",
    "enable",
    "provide",
    "implement",
    "user",
    "system",
}


def _terms(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", value.lower())
    return {word for word in words if word not in _STOP_WORDS and len(word) > 2}


def _contains_conflict_marker(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ["name", "relative_path", "excerpt"]).lower()
    return any(marker in text for marker in ["todo", "stub", "not implemented", "placeholder"])


def _is_test_evidence(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ["name", "relative_path", "kind", "excerpt"]).lower()
    return "test" in text or "/tests/" in text or text.startswith("tests/")
