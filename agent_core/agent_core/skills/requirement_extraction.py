from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from agent_core.domain.evidence import EvidenceRef
from agent_core.domain.enums import RequirementStatus
from agent_core.skills.base import BaseSkill, SkillContext, SkillResult


class RequirementExtractionInput(BaseModel):
    original_request: str = ""
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    chunk_summaries: list[dict[str, Any]] = Field(default_factory=list)
    max_requirements: int = Field(default=50, ge=1, le=200)


class NormalizedRequirement(BaseModel):
    key: str
    statement: str
    status: RequirementStatus = RequirementStatus.PROPOSED
    evidence: list[EvidenceRef] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class ExtractedPlanningItem(BaseModel):
    key: str
    text: str
    evidence: list[EvidenceRef] = Field(default_factory=list)


class RequirementExtractionOutput(BaseModel):
    requirements: list[NormalizedRequirement] = Field(default_factory=list)
    constraints: list[ExtractedPlanningItem] = Field(default_factory=list)
    assumptions: list[ExtractedPlanningItem] = Field(default_factory=list)
    decisions: list[ExtractedPlanningItem] = Field(default_factory=list)
    risks: list[ExtractedPlanningItem] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RequirementExtractionSkill(BaseSkill):
    name = "requirement_extraction"
    description = "Extracts normalized requirements and planning facts with evidence."
    input_schema = RequirementExtractionInput
    output_schema = RequirementExtractionOutput
    side_effects = False

    def can_handle(self, intent: str, context: SkillContext) -> float:
        lowered = intent.lower()
        if any(word in lowered for word in ["requirement", "scope", "constraint", "risk"]):
            return 0.92
        if context.document_ids or context.chunk_ids:
            return 0.78
        return 0.35

    async def run(
        self,
        *,
        intent: str,
        context: SkillContext,
        input_data: dict[str, Any],
    ) -> SkillResult:
        parsed = RequirementExtractionInput.model_validate(input_data or {})
        sources = list(_iter_sources(parsed))
        warnings: list[str] = []
        if not sources:
            warnings.append("No request text or document chunks were provided.")

        buckets: dict[str, list[ExtractedPlanningItem | NormalizedRequirement]] = {
            "requirements": [],
            "constraints": [],
            "assumptions": [],
            "decisions": [],
            "risks": [],
        }
        seen: set[tuple[str, str]] = set()
        counters: dict[str, int] = {}
        evidence_refs: list[EvidenceRef] = []

        for source in sources:
            evidence = EvidenceRef(
                evidence_type=source["evidence_type"],
                uri=source["uri"],
                title=source.get("title"),
                excerpt=_excerpt(source["content"]),
                metadata=source.get("metadata", {}),
            )
            evidence_refs.append(evidence)
            for line in _candidate_lines(source["content"]):
                bucket = _classify_line(line, source.get("heading_path", []))
                if bucket is None:
                    continue
                normalized = _normalize_statement(line)
                dedupe_key = (bucket, normalized.lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                key = _stable_key(bucket, normalized, counters)
                if bucket == "requirements":
                    buckets[bucket].append(
                        NormalizedRequirement(
                            key=key,
                            statement=normalized,
                            evidence=[evidence],
                            keywords=_keywords(normalized),
                        )
                    )
                else:
                    buckets[bucket].append(
                        ExtractedPlanningItem(
                            key=key,
                            text=normalized,
                            evidence=[evidence],
                        )
                    )

        if not buckets["requirements"] and parsed.original_request.strip():
            evidence = EvidenceRef(
                evidence_type="planning_request",
                uri="request:original",
                title="Original request",
                excerpt=_excerpt(parsed.original_request),
            )
            buckets["requirements"].append(
                NormalizedRequirement(
                    key="req.original-request",
                    statement=_normalize_statement(parsed.original_request),
                    evidence=[evidence],
                    keywords=_keywords(parsed.original_request),
                )
            )
            if not evidence_refs:
                evidence_refs.append(evidence)
            warnings.append("No explicit requirement markers were found; original request was captured as a requirement.")

        requirements = buckets["requirements"][: parsed.max_requirements]
        if len(buckets["requirements"]) > parsed.max_requirements:
            warnings.append(f"Requirement extraction truncated to {parsed.max_requirements} requirements.")

        output = RequirementExtractionOutput(
            requirements=requirements,  # type: ignore[arg-type]
            constraints=buckets["constraints"],  # type: ignore[arg-type]
            assumptions=buckets["assumptions"],  # type: ignore[arg-type]
            decisions=buckets["decisions"],  # type: ignore[arg-type]
            risks=buckets["risks"],  # type: ignore[arg-type]
            evidence_refs=evidence_refs,
            warnings=warnings,
        )
        return SkillResult(
            skill_name=self.name,
            success=True,
            output=output.model_dump(mode="json"),
            source_refs=[ref.model_dump(mode="json") for ref in evidence_refs],
        )


_MODAL_PATTERNS = [
    r"\bmust\b",
    r"\bshall\b",
    r"\bshould\b",
    r"\brequired\b",
    r"\bneeds? to\b",
    r"\bsupport\b",
    r"\ballow\b",
    r"\benable\b",
    r"\bprovide\b",
    r"\bimplement\b",
]
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
}


def _iter_sources(parsed: RequirementExtractionInput):
    if parsed.original_request.strip():
        yield {
            "evidence_type": "planning_request",
            "uri": "request:original",
            "title": "Original request",
            "content": parsed.original_request,
            "heading_path": [],
        }

    for index, chunk in enumerate(parsed.chunks):
        content = str(chunk.get("content") or "").strip()
        if not content:
            continue
        chunk_id = chunk.get("chunk_id") or chunk.get("id") or str(index)
        yield {
            "evidence_type": "document_chunk",
            "uri": f"document_chunk:{chunk_id}",
            "title": chunk.get("title") or "Document chunk",
            "content": content,
            "heading_path": chunk.get("heading_path") or [],
            "metadata": {
                "document_id": chunk.get("document_id"),
                "chunk_index": chunk.get("chunk_index", index),
            },
        }

    for index, summary in enumerate(parsed.chunk_summaries):
        content = str(summary.get("summary") or summary.get("content") or "").strip()
        if not content:
            continue
        yield {
            "evidence_type": "chunk_summary",
            "uri": f"chunk_summary:{summary.get('chunk_id') or index}",
            "title": summary.get("title") or "Chunk summary",
            "content": content,
            "heading_path": summary.get("heading_path") or [],
        }


def _candidate_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        line = line.strip()
        if len(line) < 8 or line.startswith("```"):
            continue
        if re.fullmatch(r"#{1,6}\s+.+", line):
            continue
        lines.append(line)
    if not lines and text.strip():
        return [text.strip()]
    return lines


def _classify_line(line: str, heading_path: list[str]) -> str | None:
    lowered = line.lower()
    heading = " ".join(heading_path).lower()
    combined = f"{heading} {lowered}"
    if any(word in combined for word in ["risk", "mitigation", "blocker"]):
        return "risks"
    if any(word in combined for word in ["assumption", "assume", "assuming"]):
        return "assumptions"
    if any(word in combined for word in ["decision", "decide", "chosen", "we will use"]):
        return "decisions"
    if any(word in combined for word in ["constraint", "must not", "cannot", "security", "compliance", "read-only"]):
        return "constraints"
    if "requirement" in heading or any(re.search(pattern, lowered) for pattern in _MODAL_PATTERNS):
        return "requirements"
    return None


def _normalize_statement(value: str) -> str:
    value = re.sub(r"^#+\s*", "", value.strip())
    value = re.sub(r"\s+", " ", value)
    return value.rstrip(".") + "."


def _stable_key(bucket: str, statement: str, counters: dict[str, int]) -> str:
    prefix = {
        "requirements": "req",
        "constraints": "con",
        "assumptions": "asm",
        "decisions": "dec",
        "risks": "risk",
    }[bucket]
    words = re.findall(r"[a-z0-9]+", statement.lower())
    meaningful = [word for word in words if word not in _STOP_WORDS][:6]
    slug = "-".join(meaningful) or "item"
    base = f"{prefix}.{slug}"[:100].rstrip("-")
    counters[base] = counters.get(base, 0) + 1
    if counters[base] == 1:
        return base
    return f"{base}-{counters[base]}"


def _keywords(value: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", value.lower())
    return sorted(dict.fromkeys(word for word in words if word not in _STOP_WORDS and len(word) > 2))[:12]


def _excerpt(value: str, limit: int = 300) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."
