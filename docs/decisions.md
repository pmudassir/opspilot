# Architecture Decision Records

Format: decision · why · alternatives · revisit when.

## ADR-001: Request is the only unit of work in V1
- **Why:** a separate Task entity creates ambiguity ("whose status is real?") with no V1 benefit.
- **Alternatives:** Request + Task now.
- **Revisit when:** one request must spawn work across several departments (likely with AI decomposition).

## ADR-002: Own auth with opaque server-side sessions
- **Why:** revocable, simple with one backend + one DB, and teaches the fundamentals.
- **Alternatives:** JWT access/refresh (hard to revoke, more moving parts); Clerk/Auth0 (faster, less learning, vendor coupling).
- **Revisit when:** SSO/enterprise login is required, or multiple services need to verify identity independently.

## ADR-003: Users are global; org membership is a separate table
- **Why:** one person can belong to several orgs; cheap now, expensive to retrofit.
- **Alternatives:** `users.organization_id` (simpler, blocks multi-org users).
- **Revisit when:** never expected; the UI org switcher comes later.

## ADR-004: Staff see all requests in their org (V1)
- **Why:** simplest correct rule; department scoping adds query and test complexity before it's needed.
- **Alternatives:** department-scoped visibility from day one.
- **Revisit when:** an org has departments that must not see each other's work.

## ADR-005: Async SQLAlchemy (asyncpg + AsyncSession)
- **Why:** FastAPI is async-native, future LLM calls are I/O-bound, and switching later means a rewrite. Lazy loading being disallowed forces explicit eager loading, which prevents N+1 queries.
- **Alternatives:** sync SQLAlchemy (simpler to debug, runs in FastAPI's threadpool).
- **Revisit when:** async complexity causes real bugs we can't reason about.

## ADR-006: Local Postgres via Docker Compose (Postgres only)
- **Why:** reproducible Postgres version and a disposable test database.
- **Alternatives:** Homebrew Postgres.
- **Revisit when:** deployment work begins (containerizing the app is a separate decision).
- **Note (2026-09-28):** Docker wasn't installed; Homebrew Postgres 17 was offered as the alternative. Kept Docker by user choice.

## ADR-007: Signup creates an org; admins add members directly
- **Why:** no email infrastructure needed in V1.
- **Alternatives:** email invitations (needs email sending + token flow).
- **Revisit when:** real external users onboard.

## ADR-008: Shared schema multi-tenancy with `organization_id` everywhere
- **Why:** simplest model; isolation enforced by TenantContext, scoped queries, composite FKs, and cross-tenant tests.
- **Alternatives:** schema-per-tenant, database-per-tenant.
- **Revisit when:** compliance or noisy-neighbor needs demand physical isolation; add RLS first.

## ADR-009: Enum-like columns are VARCHAR(32) + CHECK, not native Postgres ENUM
- **Why:** native ENUM values can't be removed or renamed without recreating the type; a CHECK constraint is swapped in an ordinary migration.
- **Alternatives:** native ENUM (slightly smaller storage, self-documenting type); lookup tables (overkill for fixed code-defined sets).
- **Revisit when:** values become per-organization data (then a table, not an enum).

## ADR-010: Tests build the schema via Alembic and truncate tables between tests
- **Why:** tests exercise the real migration path (including every downgrade) and real commits; step 6 concurrency tests need real transactions.
- **Alternatives:** `create_all()` (can drift from migrations); rollback-per-test (faster, hides commit behavior).
- **Revisit when:** the suite gets slow enough to hurt (then: rollback-per-test for pure-read tests).
