from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.enums import RepositoryAccessMode


DEFAULT_REPOSITORY_DENYLIST: tuple[str, ...] = (
    ".git",
    ".git/**",
    "**/.git",
    "**/.git/**",
    ".hg",
    ".hg/**",
    ".svn",
    ".svn/**",
    ".venv",
    ".venv/**",
    "venv",
    "venv/**",
    "__pycache__",
    "__pycache__/**",
    "**/__pycache__",
    "**/__pycache__/**",
    "node_modules",
    "node_modules/**",
    "**/node_modules",
    "**/node_modules/**",
)


class RepositoryPolicyError(ValueError):
    """Base class for repository binding and path policy failures."""


class UnknownRepositoryError(RepositoryPolicyError):
    """Raised when a repository key is not registered."""


class RepositoryPathError(RepositoryPolicyError):
    """Raised when a path is malformed or escapes its repository mount."""


class RepositoryAccessDenied(RepositoryPolicyError):
    """Raised when a requested operation violates repository policy."""


class RepositoryBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    mount_path: str = Field(min_length=1)
    access_mode: RepositoryAccessMode = RepositoryAccessMode.READ_ONLY
    write_allowlist: tuple[str, ...] = Field(default_factory=tuple)
    denylist: tuple[str, ...] = Field(default_factory=lambda: DEFAULT_REPOSITORY_DENYLIST)
    command_allowlist: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("mount_path")
    @classmethod
    def mount_path_cannot_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("mount_path cannot be blank")
        return stripped

    @field_validator("write_allowlist", "denylist", mode="before")
    @classmethod
    def normalize_glob_patterns(cls, value: object) -> tuple[str, ...]:
        values = _as_string_sequence(value)
        return tuple(_normalize_repo_pattern(pattern) for pattern in values)

    @field_validator("command_allowlist", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> tuple[str, ...]:
        commands = []
        for command in _as_string_sequence(value):
            stripped = command.strip()
            if not stripped:
                raise ValueError("command allowlist entries cannot be blank")
            if any(char.isspace() for char in stripped):
                raise ValueError(
                    "command allowlist entries must be executable names, not shell commands"
                )
            commands.append(Path(stripped).name)
        return tuple(commands)


@dataclass(frozen=True)
class ResolvedRepositoryPath:
    repository_key: str
    relative_path: str
    absolute_path: Path
    for_write: bool = False


def normalize_repository_relative_path(relative_path: str) -> str:
    raw = str(relative_path).strip()
    if "\x00" in raw:
        raise RepositoryPathError("Repository paths cannot contain NUL bytes")
    if not raw:
        raise RepositoryPathError("Repository path cannot be blank")
    windows_path = PureWindowsPath(raw)
    if PurePosixPath(raw).is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise RepositoryPathError("Repository paths must be relative")

    normalized = raw.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise RepositoryPathError("Repository paths cannot contain '..'")
    if not parts:
        return "."
    return "/".join(parts)


def resolve_repository_root(binding: RepositoryBinding) -> Path:
    try:
        root = Path(binding.mount_path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise RepositoryPathError(
            f"Repository mount does not exist or cannot be resolved: {binding.mount_path}"
        ) from exc

    if not root.is_dir():
        raise RepositoryPathError(f"Repository mount is not a directory: {root}")
    return root


def resolve_repository_path(
    binding: RepositoryBinding,
    relative_path: str,
    *,
    for_write: bool = False,
) -> ResolvedRepositoryPath:
    normalized = normalize_repository_relative_path(relative_path)
    _assert_repo_relative_policy(binding, normalized, for_write=for_write)

    root = resolve_repository_root(binding)
    candidate = root if normalized == "." else root.joinpath(*normalized.split("/"))

    try:
        if for_write and not candidate.exists():
            parent = candidate.parent.resolve(strict=True)
            _assert_contained(root, parent)
            resolved = parent / candidate.name
        else:
            resolved = candidate.resolve(strict=True)
            _assert_contained(root, resolved)
    except OSError as exc:
        raise RepositoryPathError(
            f"Repository path does not exist or cannot be resolved: {normalized}"
        ) from exc

    return ResolvedRepositoryPath(
        repository_key=binding.repository_key,
        relative_path=normalized,
        absolute_path=resolved,
        for_write=for_write,
    )


def assert_command_allowed(binding: RepositoryBinding, command: Sequence[str]) -> None:
    if not command:
        raise RepositoryAccessDenied("Command cannot be empty")

    executable = Path(str(command[0])).name
    if executable not in binding.command_allowlist:
        raise RepositoryAccessDenied(
            f"Command '{executable}' is not allowed for repository '{binding.repository_key}'"
        )


def path_matches_any(relative_path: str, patterns: Sequence[str]) -> bool:
    normalized = normalize_repository_relative_path(relative_path)
    return any(_matches_pattern(normalized, pattern) for pattern in patterns)


def _assert_repo_relative_policy(
    binding: RepositoryBinding,
    normalized_path: str,
    *,
    for_write: bool,
) -> None:
    if path_matches_any(normalized_path, binding.denylist):
        raise RepositoryAccessDenied(
            f"Repository path '{normalized_path}' is denied for repository '{binding.repository_key}'"
        )

    if not for_write:
        return

    if binding.access_mode != RepositoryAccessMode.READ_WRITE:
        raise RepositoryAccessDenied(
            f"Repository '{binding.repository_key}' is not writable"
        )
    if not binding.write_allowlist:
        raise RepositoryAccessDenied(
            f"Repository '{binding.repository_key}' has no write allowlist"
        )
    if not path_matches_any(normalized_path, binding.write_allowlist):
        raise RepositoryAccessDenied(
            f"Repository path '{normalized_path}' is outside the write allowlist"
        )


def _assert_contained(root: Path, candidate: Path) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RepositoryPathError(
            f"Repository path escapes configured mount: {candidate}"
        ) from exc


def _matches_pattern(relative_path: str, pattern: str) -> bool:
    normalized_pattern = _normalize_repo_pattern(pattern)
    if fnmatchcase(relative_path, normalized_pattern):
        return True
    if normalized_pattern.endswith("/**"):
        base = normalized_pattern[:-3]
        return relative_path == base
    return False


def _normalize_repo_pattern(pattern: str) -> str:
    raw = pattern.strip()
    if not raw:
        raise ValueError("repository path patterns cannot be blank")
    windows_path = PureWindowsPath(raw)
    if PurePosixPath(raw).is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("repository path patterns must be relative")

    normalized = raw.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError("repository path patterns cannot contain '..'")
    return "/".join(parts) if parts else "."


def _as_string_sequence(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    raise TypeError("expected a string or sequence of strings")
