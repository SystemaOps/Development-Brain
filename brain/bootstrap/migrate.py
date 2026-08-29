"""One-shot database migration runner (Phase 32).

``python -m brain.bootstrap.migrate`` runs ``alembic upgrade head`` using the
resolved settings.  The Docker image exposes this as ``brain-migrate`` so a
single migration service runs migrations before the API/worker/scheduler
replicas start (no migration races).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_migrations() -> None:
    """Run alembic upgrade head in this project."""
    root = Path(__file__).resolve().parent.parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=root,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    run_migrations()


if __name__ == "__main__":
    main()
