# Authentication

## Choice
Own email/password auth with **opaque server-side sessions** in an httpOnly cookie (ADR-002).

## Design
- Passwords hashed with argon2id. Never stored or logged in plaintext.
- Login creates a random session token; the DB stores only its **hash** + user + expiry.
  A leaked DB dump then can't be replayed as sessions.
- Cookie: `HttpOnly`, `Secure` (outside local dev), `SameSite=Lax`.
- Logout / revocation = delete the session row. This is the main advantage over stateless JWTs.
- Next.js rewrites `/api/*` to FastAPI so the cookie is same-origin.
- CSRF: SameSite=Lax + Origin check on state-changing requests.
- Login errors are generic ("invalid email or password").

## Joining an org (V1)
Signup creates a user + new org + Admin membership in one transaction. Admins add members directly. A seed script creates a demo org. Email invites later.

## Known gaps to address later
Login rate limiting / lockout, password reset, email verification, session cleanup job.
