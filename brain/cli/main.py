"""brainctl entry point (Phase 30).

``python -m brain.cli.main`` (registered as ``brainctl`` in Phase 31).
"""

from __future__ import annotations

from brain.cli.commands import build_cli


def main() -> None:
    app = build_cli()
    app()


if __name__ == "__main__":
    main()
