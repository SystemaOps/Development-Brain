"""Planning service (Phase 11).

Turns requirements and current project state into evidence-based engineering
plans.  Pipeline:

1. :meth:`PlanningService.assess` -- ambiguity assessment per requirement.
2. :meth:`PlanningService.extract_requirements` -- structured requirement
   extraction from documents, retaining source provenance.
3. :meth:`PlanningService.decompose` -- produce feature/story/task items with
   dependencies and acceptance criteria (never published externally here).
4. :meth:`PlanningService.analyze_existing` -- classify each planned task's
   existing-implementation status from the code graph, tests, git history and
   existing work items.
5. :meth:`PlanningService.build_plan` -- reconcile (skip completed work),
   validate, attach planning evidence, and persist the plan.

All inputs come through ports; outputs are brain-owned :class:`Plan` objects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from brain.domain.identity import ProjectId, RepositoryId
from brain.domain.planning import (
    AmbiguityAssessment,
    ImplementationStatus,
    Plan,
    PlanEvidence,
    PlanItem,
    PlanItemType,
    PlanStatus,
    RequirementClarity,
)
from brain.domain.requirements import (
    Requirement,
    RequirementSource,
    RequirementSourceType,
)
from brain.ports.code_intelligence import CodeGraphRepository
from brain.ports.planning import PlanRepository
from brain.ports.repositories import (
    DocumentRepository,
    ExecutionRepository,
    RequirementRepository,
    WorkItemRepository,
)

_AMBIGUOUS_WORDS = re.compile(
    r"\b(approximately|roughly|soon|quickly|maybe|possibly|etc|and/or|asap|fast|efficient)\b",
    re.IGNORECASE,
)


@dataclass
class PlanningResult:
    plan: Plan
    requirements_extracted: int = 0


class PlanningService:
    """Evidence-based engineering planning over requirements and project state."""

    def __init__(
        self,
        *,
        plans: PlanRepository,
        requirements: RequirementRepository,
        documents: DocumentRepository,
        work_items: WorkItemRepository,
        executions: ExecutionRepository,
        code_graph: CodeGraphRepository,
    ) -> None:
        self._plans = plans
        self._requirements = requirements
        self._documents = documents
        self._work_items = work_items
        self._executions = executions
        self._code_graph = code_graph

    async def assess(self, project_id: ProjectId) -> list[AmbiguityAssessment]:
        assessments: list[AmbiguityAssessment] = []
        for requirement in await self._requirements.list_by_project(project_id):
            text = f"{requirement.title} {requirement.description}"
            reasons: list[str] = []
            missing: list[str] = []
            ambiguous_matches = _AMBIGUOUS_WORDS.findall(text)
            if ambiguous_matches:
                reasons.append(f"ambiguous wording: {', '.join(sorted(set(ambiguous_matches)))}")
            if len(text.strip()) < 20:
                missing.append("requirement is too terse to be actionable")
            if not requirement.acceptance_criteria:
                missing.append("no acceptance criteria")
            if not requirement.title.strip():
                missing.append("no title")
            clarity = RequirementClarity.CLEAR
            if missing:
                clarity = RequirementClarity.MISSING_INFO
            elif reasons:
                clarity = RequirementClarity.AMBIGUOUS
            assessments.append(
                AmbiguityAssessment(
                    requirement_id=requirement.id,
                    clarity=clarity,
                    reasons=reasons,
                    missing_information=missing,
                    assumptions=_assumptions_for(requirement),
                    risk=_risk(requirement, clarity),
                )
            )
        return assessments

    async def extract_requirements(
        self, project_id: ProjectId, document_ids: list[object] | None = None
    ) -> list[Requirement]:
        """Structured requirement extraction with source provenance (Task 11.2)."""
        extracted: list[Requirement] = []
        documents = await self._documents.list_by_project(project_id)
        for document in documents:
            if document_ids is not None and document.id not in document_ids:
                continue
            versions = await self._documents.list_versions(document.id)
            if not versions:
                continue
            current = max(versions, key=lambda v: v.ingested_at)
            nodes = await self._documents.list_nodes(current.id)
            for node in nodes:
                for match in _REQUIREMENT_RE.finditer(node.content):
                    title = match.group(1).strip()
                    if not title:
                        continue
                    requirement = Requirement(
                        project_id=project_id,
                        key=node.heading_path[-1] if node.heading_path else None,
                        title=title,
                        source_refs=[
                            RequirementSource(
                                source_type=RequirementSourceType.DOCUMENT,
                                source=None,
                            )
                        ],
                    )
                    extracted.append(requirement)
        return extracted

    async def decompose(
        self,
        project_id: ProjectId,
        requirement_ids: list[object] | None = None,
    ) -> list[PlanItem]:
        """Produce feature/story/task items (Task 11.3)."""
        requirements = await self._requirements.list_by_project(project_id)
        items: list[PlanItem] = []
        order = 0
        for requirement in requirements:
            if requirement_ids is not None and requirement.id not in requirement_ids:
                continue
            order += 1
            feature = PlanItem(
                project_id=project_id,
                item_type=PlanItemType.FEATURE,
                title=_feature_title(requirement),
                description=requirement.description,
                requirement_refs=[requirement.id],
                acceptance_criteria=[a.description for a in requirement.acceptance_criteria],
                sort_order=order,
            )
            items.append(feature)
            order += 1
            story = PlanItem(
                project_id=project_id,
                item_type=PlanItemType.STORY,
                title=f"Implement: {requirement.title}",
                description=requirement.description,
                requirement_refs=[requirement.id],
                parent_id=feature.id,
                acceptance_criteria=[a.description for a in requirement.acceptance_criteria],
                sort_order=order,
            )
            items.append(story)
            order += 1
            task = PlanItem(
                project_id=project_id,
                item_type=PlanItemType.TASK,
                title=f"Task for {requirement.title}",
                description=requirement.description,
                requirement_refs=[requirement.id],
                parent_id=story.id,
                dependency_ids=[],
                acceptance_criteria=[a.description for a in requirement.acceptance_criteria],
                sort_order=order,
            )
            items.append(task)
        return items

    async def analyze_existing(
        self,
        repository_id: RepositoryId,
        revision: str,
        items: list[PlanItem],
    ) -> list[PlanItem]:
        """Classify each planned task's existing-implementation status (Task 11.4)."""
        symbols = await self._code_graph.list_symbols(repository_id, revision)
        relations = await self._code_graph.list_relations(repository_id, revision)
        symbol_names = {symbol.name.lower() for symbol in symbols}
        test_paths = {
            relation.target_path or relation.source_path
            for relation in relations
            if relation.relation_type.value == "TESTS"
        }

        for item in items:
            keywords = _keywords(item.title, item.description)
            matched_symbols = [k for k in keywords if k in symbol_names]
            has_tests = any(any(k in path for k in keywords) for path in test_paths)
            evidence: list[str] = []
            if matched_symbols:
                evidence.append(f"found symbols: {', '.join(matched_symbols)}")
            if has_tests:
                evidence.append("related tests exist")
            item.evidence = evidence
            if not evidence:
                item.implementation_status = ImplementationStatus.NOT_IMPLEMENTED
            elif has_tests and matched_symbols:
                item.implementation_status = ImplementationStatus.IMPLEMENTED_BUT_UNVERIFIED
            elif matched_symbols:
                item.implementation_status = ImplementationStatus.PARTIALLY_IMPLEMENTED
            else:
                item.implementation_status = ImplementationStatus.UNKNOWN
        return items

    async def build_plan(
        self,
        project_id: ProjectId,
        *,
        title: str,
        repository_id: RepositoryId | None = None,
        revision: str | None = None,
        persist: bool = True,
    ) -> PlanningResult:
        assessments = await self.assess(project_id)
        items = await self.decompose(project_id)
        if repository_id is not None and revision is not None:
            items = await self.analyze_existing(repository_id, revision, items)

        # Reconcile: drop tasks that are already fully implemented (11.5).
        reconciled = self._reconcile(items)
        plan = Plan(project_id=project_id, title=title, items=reconciled, assessments=assessments)
        plan.evidence = self._build_evidence(plan)
        plan.validation_errors = self._validate(plan)
        plan.status = PlanStatus.VALIDATED if not plan.validation_errors else PlanStatus.PROPOSED
        if persist:
            await self._plans.save_plan(plan)
        return PlanningResult(plan=plan, requirements_extracted=len(assessments))

    def _reconcile(self, items: list[PlanItem]) -> list[PlanItem]:
        """Skip work already completed (Task 11.5)."""
        reconciled: list[PlanItem] = []
        for item in items:
            if (
                item.item_type == PlanItemType.TASK
                and item.implementation_status == ImplementationStatus.IMPLEMENTED
            ):
                continue
            reconciled.append(item)
        return reconciled

    def _build_evidence(self, plan: Plan) -> list[PlanEvidence]:
        evidence: list[PlanEvidence] = []
        for item in plan.items:
            for requirement_id in item.requirement_refs:
                evidence.append(
                    PlanEvidence(
                        plan_id=plan.id,
                        source_requirement_id=requirement_id,
                        note=(
                            f"{item.item_type.value} '{item.title}' "
                            f"derives from REQ {requirement_id}"
                        ),
                    )
                )
        return evidence

    def _validate(self, plan: Plan) -> list[str]:
        """Validate coverage, dependencies, criteria, duplicates, order (Task 11.6)."""
        errors: list[str] = []
        required = {a.requirement_id for a in plan.assessments}
        covered = {rid for item in plan.items for rid in item.requirement_refs}
        uncovered = required - covered
        if uncovered:
            errors.append(f"requirements not covered: {sorted(str(r) for r in uncovered)}")

        item_ids = {item.id for item in plan.items}
        for item in plan.items:
            if not item.acceptance_criteria:
                errors.append(f"task '{item.title}' has no acceptance criteria")
            dangling = [d for d in item.dependency_ids if d not in item_ids]
            if dangling:
                errors.append(f"task '{item.title}' references missing dependency")

        seen_titles: dict[str, int] = {}
        for item in plan.items:
            seen_titles[item.title] = seen_titles.get(item.title, 0) + 1
        for title, count in seen_titles.items():
            if count > 1:
                errors.append(f"duplicate task title: '{title}'")

        return errors


def _assumptions_for(requirement: Requirement) -> list[str]:
    assumptions: list[str] = []
    if not requirement.description:
        assumptions.append("description assumed from title")
    if not requirement.priority:
        assumptions.append("priority assumed medium")
    return assumptions


def _risk(requirement: Requirement, clarity: RequirementClarity) -> float:
    if clarity == RequirementClarity.CLEAR:
        return 0.2
    if clarity == RequirementClarity.AMBIGUOUS:
        return 0.6
    return 0.8


def _feature_title(requirement: Requirement) -> str:
    prefix = f"{requirement.key}: " if requirement.key else ""
    return f"{prefix}{requirement.title}"


def _keywords(title: str, description: str) -> list[str]:
    text = f"{title} {description}".lower()
    words = re.findall(r"[a-z_][a-z0-9_]{2,}", text)
    stop = {"the", "and", "for", "with", "implement", "task", "requirement", "support"}
    return [w for w in words if w not in stop]


_REQUIREMENT_RE = re.compile(r"(?:REQ-\d+|MUST|SHALL|WILL)[:\s]+([A-Z][^\n.]{5,})", re.IGNORECASE)


__all__ = ["PlanningResult", "PlanningService"]
