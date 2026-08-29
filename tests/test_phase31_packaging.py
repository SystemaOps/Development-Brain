"""Phase 31 golden tests and completion gate.

The project is no longer only a library: ``[project.scripts]`` exposes
``brain-api``, ``brain-worker``, ``brain-scheduler``, and ``brainctl``; version
metadata is available; and a wheel installs into a clean environment with all
commands available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLEAN_VENV = Path(
    os.getenv(
        "BRAIN_CLEAN_VENV",
        str(Path(os.getenv("TEMP", "/tmp")) / "opencode" / "brain-clean-venv"),
    )
)


def test_version_metadata() -> None:
    from brain.version import application_version, package_version

    info = application_version()
    assert info["version"] == package_version()
    assert "version" in info
    assert "build" in info


def test_version_route_exposes_metadata() -> None:
    # The route returns the application version dict.
    import asyncio

    from brain.api.routes.system import system_version

    result = asyncio.run(system_version())
    assert result["version"]
    assert result["build"]


def test_api_runner_settings() -> None:
    from brain.api.runner import DEFAULT_PORT, RunnerSettings, runner_settings

    settings = runner_settings()
    assert isinstance(settings, RunnerSettings)
    assert settings.port == DEFAULT_PORT
    assert settings.host
    assert settings.workers >= 1


def test_project_scripts_are_declared() -> None:
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]
    assert scripts["brain-api"] == "brain.api.runner:main"
    assert scripts["brain-worker"] == "brain.workers.main:main"
    assert scripts["brain-scheduler"] == "brain.scheduler.main:main"
    assert scripts["brainctl"] == "brain.cli.main:main"


def test_clean_install_wheel_and_commands() -> None:
    """Build the wheel, install into a clean environment, verify commands."""
    uv = shutil.which("uv")
    assert uv, "uv executable required"
    build_dir = ROOT / "dist"
    if not list(build_dir.glob("*.whl")):
        subprocess.run([uv, "build"], cwd=ROOT, check=True, capture_output=True)
    wheel = next(build_dir.glob("brain-*.whl"))
    venv_dir = CLEAN_VENV
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    subprocess.run([uv, "venv", str(venv_dir)], check=True, capture_output=True)
    python = venv_dir / "Scripts" / "python.exe"
    subprocess.run(
        [uv, "pip", "install", "--python", str(python), str(wheel)],
        check=True,
        capture_output=True,
    )
    scripts = venv_dir / "Scripts"
    for name in ("brain-api", "brain-worker", "brain-scheduler", "brainctl"):
        exe = scripts / f"{name}.exe"
        assert exe.exists(), f"missing script {name}"
    result = subprocess.run(
        [str(scripts / "brainctl.exe"), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert result.returncode == 0
    assert "project" in result.stdout
