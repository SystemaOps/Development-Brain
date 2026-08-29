# Architecture

## System overview

```text
router (login endpoint)
  -> AuthService (auth.service)
      -> UserRepository (users.user_model)
      -> SecurityPolicy (auth.security)
```

- `AuthService` validates credentials against the `UserRepository`.
- `SecurityPolicy` defines the lockout policy constants (threshold, duration).
- Failed attempts are recorded per account by `AuthService`.

## Account locking

The lockout policy is centralized in `auth.security.SecurityPolicy`:

- `MAX_FAILED_ATTEMPTS = 5`
- `LOCKOUT_DURATION_MINUTES = 15`

The implementation currently tracks attempts but does not enforce the
lockout (partial implementation).