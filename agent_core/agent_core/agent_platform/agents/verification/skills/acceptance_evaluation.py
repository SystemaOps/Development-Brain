from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.verification.contracts import (
    AcceptanceCoverageAssessment,
    AcceptanceCriterionAssessment,
    AcceptanceCriterionOutcome,
    VerificationFinding,
)
from agent_core.schemas import AcceptanceCriterionSpec


class AcceptanceEvidence(BaseModel):
    source: str
    content: str


class AcceptanceEvaluationInput(BaseModel):
    criteria: list[AcceptanceCriterionSpec] = Field(default_factory=list)
    evidence: list[AcceptanceEvidence] = Field(default_factory=list)


class AcceptanceEvaluationOutput(BaseModel):
    assessment: AcceptanceCoverageAssessment
    findings: list[VerificationFinding] = Field(default_factory=list)


class AcceptanceEvaluationSkill:
    name = "acceptance_evaluation"
    required_dependencies: tuple[str, ...] = ()

    async def run(
        self,
        input_data: AcceptanceEvaluationInput,
    ) -> AcceptanceEvaluationOutput:
        criteria = [
            self._assess_criterion(criterion, input_data.evidence)
            for criterion in input_data.criteria
        ]
        findings = [
            VerificationFinding(
                severity="error",
                code="acceptance_criterion_unmet",
                message=(
                    "Acceptance criterion is not supported by repository or "
                    f"execution evidence: {criterion.statement}"
                ),
                acceptance_criterion_key=criterion.criterion_key,
            )
            for criterion in criteria
            if criterion.outcome == AcceptanceCriterionOutcome.UNSATISFIED
        ]
        satisfied_count = sum(
            criterion.outcome == AcceptanceCriterionOutcome.SATISFIED for criterion in criteria
        )
        assessment = AcceptanceCoverageAssessment(
            criteria=criteria,
            total_count=len(criteria),
            satisfied_count=satisfied_count,
            unsatisfied_count=len(criteria) - satisfied_count,
            mandatory_criteria_satisfied=not findings,
        )
        return AcceptanceEvaluationOutput(
            assessment=assessment,
            findings=findings,
        )

    @staticmethod
    def _assess_criterion(
        criterion: AcceptanceCriterionSpec,
        evidence: list[AcceptanceEvidence],
    ) -> AcceptanceCriterionAssessment:
        terms = [
            term for term in re.findall(r"[a-z0-9]+", criterion.statement.lower()) if len(term) > 3
        ]
        required_matches = max(1, min(3, len(terms) // 2)) if terms else 0
        matched_terms = sorted(
            {term for term in terms if any(term in item.content.lower() for item in evidence)}
        )
        evidence_sources = sorted(
            {
                item.source
                for item in evidence
                if any(term in item.content.lower() for term in matched_terms)
            }
        )
        satisfied = bool(terms) and len(matched_terms) >= required_matches
        if satisfied:
            rationale = f"Matched {len(matched_terms)} evidence terms; {required_matches} required."
        elif not terms:
            rationale = "Criterion has no discriminating terms that can be verified."
        else:
            rationale = f"Matched {len(matched_terms)} evidence terms; {required_matches} required."
        return AcceptanceCriterionAssessment(
            criterion_key=criterion.key,
            statement=criterion.statement,
            verification_method=criterion.verification_method,
            outcome=(
                AcceptanceCriterionOutcome.SATISFIED
                if satisfied
                else AcceptanceCriterionOutcome.UNSATISFIED
            ),
            rationale=rationale,
            matched_terms=matched_terms,
            required_match_count=required_matches,
            evidence_sources=evidence_sources,
        )
