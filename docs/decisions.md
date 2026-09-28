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

## ADR-011: Errors use FastAPI's `{"detail": ...}` shape; success bodies are the resource itself
- **Why:** it's the framework convention, so validation errors (422) and our errors share one shape with no custom layer.
- **Alternatives:** a `{success, data, error}` envelope on every response (extra wrapping, duplicates HTTP status semantics).
- **Revisit when:** clients need machine-readable error codes. Then add a `code` field alongside `detail`.

## ADR-012: Keyset (cursor) pagination for request lists
- **Why:** stable while new requests arrive (OFFSET repeats or skips rows), and O(page) via the `(organization_id, created_at DESC, id DESC)` index instead of scanning skipped rows.
- **Alternatives:** OFFSET/LIMIT (simple, supports "jump to page N", unstable and slower for deep pages).
- **Revisit when:** users genuinely need page numbers or arbitrary sort orders (each sort order needs its own keyset + index).

## ADR-013: The audit log is append-only at the database level
- **Why:** history is only trustworthy if nobody can rewrite it, including buggy code, scripts and manual SQL. A trigger rejects UPDATE/DELETE on `request_events`.
- **Alternatives:** convention only (no API to edit events); REVOKE privileges from the app role (needs separate DB roles for migrations vs. runtime).
- **Revisit when:** we split DB roles (then also REVOKE), or need data-retention deletion (a controlled, audited procedure).

## ADR-014: Lifecycle transitions use optimistic compare-and-set, not row locks
- **Why:** conflicts are rare; the check (permissions, state, department membership) runs without holding a lock; a 409 tells the client to reload. The race is on one row, so a guarded UPDATE is sufficient.
- **Alternatives:** `SELECT … FOR UPDATE` before checking (pessimistic, also correct, holds a lock during checks); a `version` column (more general, covers edits to any field).
- **Revisit when:** requests gain editable fields (title, priority): add a `version` column and include it in the guard.
- **Contrast:** member changes (ADR none, see multi-tenancy.md) use a lock because that race is write skew across *different* rows.

## ADR-015: One endpoint per lifecycle action
- **Why:** each action has distinct authorization and body; `POST …/assign`, `…/claim` make rules explicit and discoverable in OpenAPI.
- **Alternatives:** `PATCH /requests/{id} {status}` (generic, hides which transitions and rules exist).
- **Revisit when:** never expected; new actions add endpoints plus a row in `TRANSITIONS`.

## ADR-016: Client-side data fetching with TanStack Query, via a same-origin proxy
- **Why:** a logged-in ops tool gains nothing from SSR/SEO; the browser sends the session cookie itself, so auth needs no server-side cookie forwarding. TanStack Query handles caching, loading/error states and invalidation after mutations.
- **Alternatives:** Server Components + Server Actions (forward the cookie server-side, two network hops, more caching layers); `fetch` in `useEffect` (race conditions, stale data).
- **Revisit when:** public/SEO pages appear, or first-load performance matters enough to render data on the server.

## ADR-017: Tailwind CSS with a few hand-built UI primitives
- **Why:** small surface we fully understand (button, field, feedback); avoids a generic component-library look and dependency sprawl.
- **Alternatives:** shadcn/ui (faster polished widgets, more files/deps); CSS Modules (no framework, verbose).
- **Revisit when:** we need complex accessible widgets (combobox, date picker): adopt headless primitives for those only.

## ADR-018: Frontend API types generated from the backend's OpenAPI schema
- **Why:** one source of truth. A renamed field breaks the frontend build, not production.
- **Alternatives:** hand-written TS types (drift silently); a shared schema language (overkill for one backend).
- **Revisit when:** multiple clients or public API versioning.

## ADR-019: The API tells the client which actions it may take (`allowed_actions`)
- **Why:** the lifecycle rules (role, state, assignee, requester-while-open, department) are subtle; re-implementing them in the frontend would drift. The same pure rule functions both enforce actions and compute `allowed_actions`. A property test attempts every action for every (state, user) and asserts success ⇔ advertised.
- **Alternatives:** frontend derives buttons from role/status (duplicated business logic); show all buttons and rely on errors (poor UX).
- **Revisit when:** a client needs the *reason* an action is unavailable (return reasons alongside).
- **Extended (Phase 2 Step 4):** `/me` also returns each membership's `permissions` from `ROLE_PERMISSIONS`, so navigation and admin controls don't compare role names either.
