"""Source-control adapters.

:class:`~brain.adapters.git.local.LocalGitAdapter` implements the
:class:`~brain.ports.source_control.SourceControlPort` on the local ``git``
CLI; :class:`~brain.adapters.git.scanner.RepositoryScanner` summarizes a
checked-out tree into a canonical :class:`RepositorySnapshot`.  Remote
providers (GitLab, GitHub) implement the same port contract behind these
adapters, never leaking provider types into the domain.
"""

from brain.adapters.git.local import GitError, LocalGitAdapter
from brain.adapters.git.scanner import RepositoryScanner

__all__ = ["GitError", "LocalGitAdapter", "RepositoryScanner"]
