"""Knowledge graph schema: labels and controlled relationship vocabulary.

The brain's graph never invents relationship types: every edge uses one of the
:class:`RelationType` members so projections and queries share a stable
contract, and every code-related edge carries revision/provenance (origin +
confidence) so facts stay exact per repository revision.
"""

from __future__ import annotations

from enum import StrEnum


class GraphLabel(StrEnum):
    """Canonical node labels projected into the knowledge graph."""

    PROJECT = "Project"
    REQUIREMENT = "Requirement"
    WORK_ITEM = "WorkItem"
    DECISION = "Decision"
    SYSTEM = "System"
    COMPONENT = "Component"
    INTERFACE = "Interface"
    RESOURCE = "Resource"
    REPOSITORY = "Repository"
    FILE = "File"
    SYMBOL = "Symbol"
    TEST = "Test"
    DOCUMENT = "Document"
    DOCUMENT_NODE = "DocumentNode"
    EXECUTION = "Execution"
    ARTIFACT = "Artifact"
    EVIDENCE = "Evidence"
    ACTOR = "Actor"


class RelationType(StrEnum):
    """Controlled relationship vocabulary (Task 8.2)."""

    PART_OF = "PART_OF"
    DEPENDS_ON = "DEPENDS_ON"
    IMPLEMENTS = "IMPLEMENTS"
    MODIFIES = "MODIFIES"
    CONSTRAINS = "CONSTRAINS"
    CALLS = "CALLS"
    IMPORTS = "IMPORTS"
    READS = "READS"
    WRITES = "WRITES"
    PROVIDES = "PROVIDES"
    CONSUMES = "CONSUMES"
    TESTS = "TESTS"
    VALIDATES = "VALIDATES"
    VERIFIED_BY = "VERIFIED_BY"
    REFERENCES = "REFERENCES"
    DERIVED_FROM = "DERIVED_FROM"
    SUPERSEDES = "SUPERSEDES"
    ASSIGNED_TO = "ASSIGNED_TO"
    PRODUCED_BY = "PRODUCED_BY"
    SERVICE_CALLS = "SERVICE_CALLS"
    QUERY_ACCESSES = "QUERY_ACCESSES"
    PUBLISHES_TO = "PUBLISHES_TO"
    CONSUMES_FROM = "CONSUMES_FROM"


__all__ = ["GraphLabel", "RelationType"]
