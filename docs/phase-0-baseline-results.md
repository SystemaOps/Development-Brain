# Phase 0 Baseline Results

Baseline date: 2026-07-20

Environment:

- Working directory: `C:\repo_gitlab\Ada`
- Python: `Python 3.11.3`
- Active shell: PowerShell
- The checked-in `.venv` points to a missing Python 3.12 executable and was not used.
- A temporary verification environment was created outside the repository at `%TEMP%\ada-codex-phase0-venv-py311`.
- Planning-core dependencies were installed from `agent_core/requirements.txt` into that temporary environment.

## Commands Run

### Legacy Smoke Script

Command:

```powershell
python test_ada.py
```

Result: failed before running assertions.

Observed failure:

```text
UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'
```

Interpretation:

- The script prints Unicode check/cross symbols.
- The active Windows console encoding is CP1252.
- This is an environment/output encoding issue, not evidence that the legacy Ada functionality failed.

Rerun command:

```powershell
$env:PYTHONIOENCODING='utf-8'; python test_ada.py
```

Result: passed.

Observed summary:

```text
Tests passed: 3/3
All tests passed! Ada Coding Agent is working correctly.
```

### Pytest Discovery For New Tests

Command:

```powershell
python -m pytest -q tests
```

Initial result before dependency setup: failed.

Observed failure:

```text
C:\Python311\python.exe: No module named pytest
```

Interpretation:

- The Phase 0 pytest import smoke test has been added under `tests/`.
- It cannot run until development dependencies are installed.

Rerun command after installing dependencies into the temporary venv:

```powershell
%TEMP%\ada-codex-phase0-venv-py311\Scripts\python.exe -m pytest -q tests
```

Result after source import fixes: passed.

Observed summary:

```text
1 passed in 0.73s
```

### Pytest Discovery For Repository

Command:

```powershell
python -m pytest -q
```

Initial result before dependency setup: failed.

Observed failure:

```text
C:\Python311\python.exe: No module named pytest
```

Interpretation:

- Repository-wide pytest discovery is currently blocked by missing `pytest`.
- `test_ada.py` will also be discovered by pytest because it contains top-level `test_*` functions.

Rerun command after installing dependencies into the temporary venv:

```powershell
%TEMP%\ada-codex-phase0-venv-py311\Scripts\python.exe -m pytest -q
```

Result: passed with warnings.

Observed summary:

```text
4 passed, 3 warnings in 0.79s
```

Warnings:

- `test_ada.py::test_imports` returns `bool` instead of using assertions.
- `test_ada.py::test_agent_functionality` returns `bool` instead of using assertions.
- `test_ada.py::test_config` returns `bool` instead of using assertions.

### Direct Core Import Probe

Command:

```powershell
$env:PYTHONPATH='C:\repo_gitlab\Ada\agent_core'
$env:DATABASE_URL='postgresql+asyncpg://coding_agent:change-me@localhost:5432/coding_agent'
$env:LLM_BASE_URL='http://localhost:8080/v1'
$env:LLM_MODEL='local-coding-model'
$env:LLM_API_KEY='local-not-secret'
$env:OPENPROJECT_BASE_URL='http://localhost:8081'
$env:OPENPROJECT_API_KEY='placeholder-key'
$env:NEO4J_URI='bolt://localhost:7687'
$env:NEO4J_USER='neo4j'
$env:NEO4J_PASSWORD='change-me'
$env:NEO4J_DATABASE='neo4j'
python -c "import importlib; modules=['agent_core.main','agent_core.models','agent_core.schemas','agent_core.skills','agent_core.workflow.graph','agent_core.workflow.runner','agent_core.workflow.state']; [importlib.import_module(m) for m in modules]; print('core import probe passed')"
```

Initial result before dependency setup: failed.

Observed failure:

```text
ModuleNotFoundError: No module named 'fastapi'
```

Interpretation:

- The import probe is now documented and represented as `tests/test_import_smoke.py`.
- It could not pass in the active Python environment until planning-core dependencies were installed.
- After dependency setup, the import smoke test exposed two source issues that have been fixed:
- `agent_core/agent_core/workflow/__init__.py` contained invalid stray text.
- `agent_core/agent_core/workflow/routing.py` did not define the `route_after_skill` function imported by `workflow/graph.py`.

## Phase 0 Baseline Status

- Legacy Ada smoke behavior is functional when the console encoding supports the script output.
- Planning-core import smoke coverage exists and passes in the temporary verification environment.
- Repository-wide pytest discovery passes in the temporary verification environment.
- No database, Docker Compose, OpenProject, Redis, Neo4j, Weaviate, or LLM integration checks were run in Phase 0.
- Runtime source changes were limited to fixing import blockers in `workflow/__init__.py` and `workflow/routing.py`.

## Required Before Phase 1 Verification

- Repair or recreate the repository `.venv`, or standardize on a documented external virtual environment.
- Decide whether to keep `test_ada.py` as a pytest-discovered test or move it to a smoke-script location.
- Decide whether to replace Unicode status symbols in `test_ada.py` with ASCII or require UTF-8 console output.
