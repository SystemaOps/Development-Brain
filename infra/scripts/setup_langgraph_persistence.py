#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "agent_core"
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


def load_env_file(path: Path) -> int:
    if not path.exists():
        return 0

    loaded = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if not key or key in os.environ:
            continue

        os.environ[key] = value
        loaded += 1

    return loaded


def redact_database_uri(uri: str) -> str:
    parsed = urlsplit(uri)
    if not parsed.password:
        return uri

    username = parsed.username or ""
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    userinfo = f"{username}:***@" if username else "***@"
    netloc = f"{userinfo}{hostname}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize LangGraph PostgreSQL checkpoint and store tables.",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help=(
            "PostgreSQL connection URI. Defaults to CHECKPOINT_DATABASE_URL, "
            "LANGGRAPH_POSTGRES_DSN, or DATABASE_URL from the environment."
        ),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Environment file to load before resolving settings. Defaults to .env.",
    )
    parser.add_argument(
        "--no-env-file",
        action="store_true",
        help="Do not load an environment file.",
    )
    parser.add_argument(
        "--checkpointer-only",
        action="store_true",
        help="Only initialize AsyncPostgresSaver tables, not AsyncPostgresStore tables.",
    )
    return parser


async def run(args: argparse.Namespace) -> None:
    if str(PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(PACKAGE_ROOT))

    if not args.no_env_file:
        loaded = load_env_file(args.env_file)
        if loaded:
            print(f"Loaded {loaded} values from {args.env_file}")

    database_uri = args.database_url.strip()
    if not database_uri:
        from agent_core.workflow.checkpointer import get_checkpoint_database_url

        database_uri = get_checkpoint_database_url()

    database_uri = normalize_database_uri(database_uri)

    from agent_core.workflow.persistence_setup import initialize_langgraph_persistence

    result = await initialize_langgraph_persistence(
        database_uri,
        include_store=not args.checkpointer_only,
    )

    print(f"Initialized LangGraph persistence at {redact_database_uri(result.database_uri)}")
    print(f"Checkpointer setup: {result.checkpointer_setup}")
    print(f"Store setup: {result.store_setup}")


def normalize_database_uri(database_uri: str) -> str:
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", database_uri, count=1)


def main() -> None:
    parser = build_parser()
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
