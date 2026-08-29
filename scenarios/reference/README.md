# Phase 39 Reference Scenario

The seed package for the full reference end-to-end environment.

## Layout

```text
scenarios/reference/
  seed.py                  registers project/repository/requirement/work item
  seed_repository/         the sample login service repository (partial impl)
    requirements.md        FR-1 account locking, FR-2 login
    docs/architecture.md   system architecture
    docs/adr/0001-auth.md  architecture decision record
    src/auth/              login flow + attempt tracking (PARTIAL)
    src/users/             user model + repository
    src/unrelated/         intentionally unrelated module
    tests/test_auth.py     related tests
    config/settings.py     runtime configuration
```

## Run

```bash
uv run python -m scenarios.reference.seed --project e2e-demo
```

## What it proves

- The Brain discovers the partial implementation of account locking
  (FR-1/AC-1..AC-4 missing) from the repository alone.
- Context for the work item includes the requirement, auth service, user
  model, security config and related tests, and ranks the unrelated module
  last.
- The deterministic scenario (tests/test_phase39_reference_env.py) walks
  execute -> verify FAIL -> retry -> PASS -> PR -> merge -> re-ingest, and
  the human feedback loop.