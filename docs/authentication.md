# Authentication

## Choice
Own email/password auth with **opaque server-side sessions** in an httpOnly cookie (ADR-002).
Code: `backend/app/auth/`.

## Endpoints (`/api/v1/auth`)
| Method | Path | Result |
|---|---|---|
| POST | `/signup` | 201 + cookie. Creates user + org + admin membership + session in **one transaction**. Duplicate email → 409 |
| POST | `/login` | 200 + cookie. Any failure → 401 `Invalid email or password` |
| POST | `/logout` | 204. Deletes the session row (revocation), clears cookie. Idempotent |
| GET | `/me` | 200: user + active memberships (org, role, `permissions`). 401 without a valid session |

## Design
- **Passwords:** argon2id (`argon2-cffi` defaults, ~64 MiB). Hashing runs in a thread pool so it doesn't block the event loop. Length 12–128, no composition rules (NIST 800-63B).
- **Enumeration:** wrong password and unknown email return identical responses; unknown emails are verified against a dummy hash so timing matches.
- **Sessions:** `secrets.token_urlsafe(32)` in cookie `opspilot_session`; table `auth_sessions` stores only `sha256(token)` + `expires_at` (7 days, fixed). Users deleted → sessions CASCADE.
- **Cookie:** `HttpOnly`, `SameSite=Lax`, `Secure` in production, `Path=/`.
- **CSRF:** SameSite=Lax + `app/csrf.py` rejects POST/PUT/PATCH/DELETE whose `Origin` isn't in `ALLOWED_ORIGINS`.
- **Emails:** validated with `email-validator`, lowercased before storage (DB CHECK enforces it).
- **Uniqueness races:** signup doesn't pre-check the email; the UNIQUE constraint decides, and the IntegrityError becomes 409.

## Joining an org (V1)
Signup creates a user + new org + Admin membership. Admins add members directly (Step 4). Email invites later.

## Known gaps (deliberate, for later)
- Signup returns 409 for a registered email, which reveals that the account exists. Closing it needs email verification.
- No login rate limiting / lockout yet: brute force is only slowed by argon2.
- No password reset, email verification, or "log out everywhere."
- Expired `auth_sessions` rows are never cleaned up (needs a periodic job).
- Fixed 7-day expiry; no sliding/idle timeout.
