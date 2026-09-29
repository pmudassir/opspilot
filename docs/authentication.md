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

## Login throttling (`app/auth/throttling.py`)
Failed attempts within 15 minutes, stored in `login_attempts` (Postgres: shared by all workers, survives restarts):
| Rule | Limit | Stops |
|---|---|---|
| per (email, IP) | 5 | one guesser, one account |
| per IP | 30 | one address trying many accounts (credential stuffing) |
| per email | 20 | many addresses against one account (IP rotation or spoofing). Trade-off: an attacker can lock an account for ≤ 15 min |

- Over a limit: **429** + `Retry-After` (seconds until the oldest counted failure leaves the window).
- Checked **before** the password hash: throttled requests cost no argon2 work and aren't recorded.
- Unknown emails are throttled exactly like real ones: the 429 doesn't reveal whether an account exists.
- Concurrent attempts can slightly exceed a limit (check-then-insert); acceptable for throttling.

### Client IP: deployment requirement
- The Next.js rewrite proxy does **not** add the client's IP and **passes a client-supplied `X-Forwarded-For` through unchanged** (verified).
- Uvicorn trusts `X-Forwarded-For` only from `FORWARDED_ALLOW_IPS` (default `127.0.0.1`) and uses the right-most address that isn't a trusted proxy (verified: `1.1.1.1, 2.2.2.2` → `2.2.2.2`; `1.1.1.1, 127.0.0.1` → `1.1.1.1`).
- **Production:** put an edge proxy / load balancer in front that *appends* the real client IP, and set `FORWARDED_ALLOW_IPS` to exactly the edge proxy + Next.js addresses. Then spoofed entries (to the left) are ignored.
- **Local dev:** nothing appends the IP, so every request is `127.0.0.1` and a client can spoof the header. The per-email rule bounds guessing regardless.

## Cleanup
`uv run python -m scripts.cleanup_expired` deletes expired sessions and login attempts older than 30 days. Idempotent; run daily (cron). Login also removes the signing-in user's expired sessions.

## Joining an org (V1)
Signup creates a user + new org + Admin membership. Admins add members directly (Step 4). Email invites later.

## Known gaps (deliberate, for later)
- Signup returns 409 for a registered email, which reveals that the account exists. Closing it needs email verification.
- Signup itself isn't rate limited (account-creation spam).
- No password reset, email verification, or "log out everywhere."
- Fixed 7-day expiry; no sliding/idle timeout.
