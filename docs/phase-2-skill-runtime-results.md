# Phase 2 Skill Runtime Results

Baseline date: 2026-07-20

## Scope Completed

- Added `SkillManifest` contracts and built-in manifest loading.
- Added one manifest per required planning skill under `agent_core/agent_core/skills/manifests`.
- Marked currently runnable skills as `implemented`:
- `ambiguity_assessment`
- `planning_decomposition`
- `document_ingestion`
- Marked required but empty-placeholder skills as `planned`:
- `requirement_extraction`
- `repository_inspection`
- `implementation_status_classification`
- `dependency_validation`
- `plan_validation`
- `openproject_projection`
- `neo4j_projection`
- `weaviate_projection`
- `context_capsule`
- Updated `SkillContext` and `SkillResult` to use `Field(default_factory=...)` for mutable fields.
- Added skill input/output validation hooks to `BaseSkill`.
- Updated `SkillRegistry` to load manifests, reject duplicate skills, reject planned-skill registration, and validate schema/side-effect compatibility.
- Added `AgentRegistry` and default planning/coding/verification agent definitions.
- Added `SkillNodeAdapter` for generic workflow skill execution.
- Wired the existing planning workflow node through `SkillNodeAdapter`.
- Added opt-in constructor-aware registration for database-backed `document_ingestion`.
- Added injectable workflow dependencies so planning graphs can run with fake skill registries and fake services.
- Added fake-skill runtime tests for input/output validation.
- Added fake planning workflow execution coverage.

## Runtime Compatibility Notes

- `build_skill_registry()` still registers only the currently runnable default planning workflow skills: `ambiguity_assessment` and `planning_decomposition`.
- `document_ingestion` is declared as implemented and can be registered with `include_database_skills=True` plus a database session, but it is not enabled in the default graph yet because the current graph does not process its output.
- Planned manifests make missing skill work explicit without pretending empty modules are runnable.
- Current graph state transitions remain unchanged after skill execution.

## Verification

Environment:

```text
C:\repo_gitlab\Ada\.venv
```

Command:

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -m pytest -q
```

Result:

```text
14 passed, 3 warnings in 1.07s
```

Warnings:

- `test_ada.py::test_imports` returns `bool` instead of using assertions.
- `test_ada.py::test_agent_functionality` returns `bool` instead of using assertions.
- `test_ada.py::test_config` returns `bool` instead of using assertions.

Alembic history sanity check:

```powershell
cd agent_core
..\.venv\Scripts\python.exe -m alembic -c alembic.ini history
```

Result:

```text
<base> -> 0001_current_baseline (head), current baseline schema
```

## Remaining Phase 2 Work

- Add contract tests for each implemented production skill.
- Add negative tests for malformed built-in manifest files.
- Move direct LLM planning fallback behavior behind a skill or compatibility adapter.
- Add skill-run persistence and audit records.
