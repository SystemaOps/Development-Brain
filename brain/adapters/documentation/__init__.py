"""Documentation adapters (Phase 15).

Git Markdown (repository docs) and XWiki providers implement the
``DocumentationPort``; both normalize into canonical ``SourceArtifact`` so the
brain works without any external wiki and can ingest them when configured.
"""

from brain.adapters.documentation.git_markdown import (
    GitMarkdownDocumentationAdapter,
    GitMarkdownTransport,
)
from brain.adapters.documentation.xwiki import (
    XWikiDocumentationAdapter,
    XWikiTransport,
)

__all__ = [
    "GitMarkdownDocumentationAdapter",
    "GitMarkdownTransport",
    "XWikiDocumentationAdapter",
    "XWikiTransport",
]
