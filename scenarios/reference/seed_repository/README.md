# e2e-demo: Login Service

Sample repository for the Phase 39 reference end-to-end scenario.

Implements a login service with **partial** account-locking: failed attempts
are tracked but the account is never locked after five failures.

## Layout

```text
README.md
requirements.md          requirements the Brain must discover
docs/
  architecture.md         system architecture (auth service, user model)
  adr/0001-auth.md        architecture decision record
src/
  auth/service.py         login flow + attempt tracking (PARTIAL implementation)
  auth/security.py        security configuration (lockout policy constants)
  users/user_model.py     user model + repository
  unrelated/notifications.py   intentionally unrelated module
tests/
  test_auth.py            related tests
config/
  settings.py             runtime configuration
```

## Run the tests

```bash
uv run pytest tests
```