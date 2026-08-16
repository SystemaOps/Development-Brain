"""Work-management adapters (Phase 14).

OpenProject and Jira providers behind the ``WorkManagementPort``.  Both share
the same contract so switching ``work_management.provider`` never changes the
planning/context/execution/verification services.
"""

from brain.adapters.work_management.jira import JiraAdapter, JiraTransport
from brain.adapters.work_management.openproject import (
    OPENPROJECT_MAPPING,
    OpenProjectAdapter,
    OpenProjectTransport,
)

__all__ = [
    "JiraAdapter",
    "JiraTransport",
    "OPENPROJECT_MAPPING",
    "OpenProjectAdapter",
    "OpenProjectTransport",
]
