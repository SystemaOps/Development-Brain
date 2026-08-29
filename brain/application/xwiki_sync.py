"""XWiki canonical mapping and sync (Phase 35).

Normalizes XWiki pages into canonical ``SourceArtifact``/``ParsedDocument``
(Task 35.3), emits ``DocumentChanged`` events for changed pages (Task 35.4),
maps spaces to projects via ``ExternalReference`` (Task 35.5), and applies the
knowledge publication policy (Task 35.6): not every observation is published
to XWiki.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from brain.domain.documents import DocumentType, SourceArtifact
from brain.domain.events import EventEnvelope, EventType
from brain.domain.external_reference import ExternalReference
from brain.domain.observations import Observation, ObservationType
from brain.ports.event_bus import EventBus


class XWikiMappingService:
    """Builds canonical documents/events from XWiki pages."""

    def __init__(self, *, wiki: str = "xwiki", event_bus: EventBus | None = None) -> None:
        self._wiki = wiki
        self._event_bus = event_bus

    def ref(self, page_id: str) -> ExternalReference:
        """ExternalReference is the only identity for XWiki pages (Task 35.5)."""
        return ExternalReference(
            provider="xwiki",
            external_id=page_id,
            external_type="page",
            namespace=self._wiki,
        )

    def to_source_artifact(self, page: dict[str, object]) -> SourceArtifact:
        """Normalize an XWiki page into a canonical SourceArtifact (Task 35.3)."""
        page_id = str(page.get("id") or page.get("reference") or "")
        content = str(page.get("content") or page.get("source") or "")
        return SourceArtifact(
            source_uri=page_id,
            provider="xwiki",
            mime_type="text/html",
            file_name=page_id,
            revision=str(page.get("version") or ""),
            content=content.encode("utf-8"),
            metadata={
                "wiki": self._wiki,
                "title": page.get("title"),
                "parent": page.get("parent"),
            },
        )

    def document_type_for_page(self, page: dict[str, object]) -> DocumentType:
        """Infer a document type from the page's space/title."""
        page_id = str(page.get("id") or page.get("reference") or "").lower()
        if "adr" in page_id or "decision" in page_id:
            return DocumentType.ADR
        if "requirement" in page_id or "req-" in page_id:
            return DocumentType.REQUIREMENTS
        if "architecture" in page_id:
            return DocumentType.ARCHITECTURE
        return DocumentType.GENERAL

    async def emit_changed(
        self, ref: ExternalReference, *, since: datetime | None = None
    ) -> EventEnvelope:
        """Emit a canonical DocumentChanged event for a changed page (Task 35.4)."""
        envelope = EventEnvelope(
            event_type=EventType.DOCUMENT_CHANGED,
            correlation_id=uuid.uuid4(),
            source="xwiki.sync",
            payload={
                "provider": "xwiki",
                "external_id": ref.external_id,
                "namespace": ref.namespace,
                "since": since.isoformat() if since else None,
            },
        )
        if self._event_bus is not None:
            await self._event_bus.publish(envelope)
        return envelope


class XWikiPublicationPolicy:
    """Which observations are allowed to be published to XWiki (Task 35.6).

    INTERNAL observations are never published; TEAM/IMPORTANT observations are
    published only for knowledge-relevant types.
    """

    PUBLISHABLE_TYPES = {
        ObservationType.ARCHITECTURE_VIOLATION,
        ObservationType.CONFLICT,
        ObservationType.DEPENDENCY_DISCOVERED,
        ObservationType.HUMAN_ACTION_REQUIRED,
    }

    @classmethod
    def may_publish(cls, observation: Observation) -> bool:
        """Decide whether an observation should reach XWiki."""
        if observation.observation_type not in cls.PUBLISHABLE_TYPES:
            return False
        # Knowledge publication is an explicit choice: the caller sets
        # visibility; INTERNAL never goes to XWiki.
        return observation.visibility.value != "internal"


__all__ = ["XWikiMappingService", "XWikiPublicationPolicy"]
