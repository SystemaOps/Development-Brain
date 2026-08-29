# Requirements

## FR-1: Account locking after five failed login attempts

**ID**: REQ-ACCOUNT-LOCK

After five consecutive failed login attempts on an account, the account MUST
be locked for 15 minutes. Further login attempts during the lockout MUST be
rejected with a `LockedOut` error, even if the credentials are correct.

### Acceptance criteria

- AC-1: A fifth failed attempt locks the account.
- AC-2: Locked accounts reject login attempts with `LockedOut`.
- AC-3: Lockout expires after 15 minutes.
- AC-4: Failed attempts before the lockout are counted per account.

## FR-2: Successful login returns the user

**ID**: REQ-LOGIN

A successful login returns the authenticated user.

### Acceptance criteria

- AC-5: Correct credentials return the user.
- AC-6: Incorrect credentials raise `AuthenticationError` and record a
  failed attempt.