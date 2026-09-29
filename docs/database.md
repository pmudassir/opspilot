# Database

## Entities
| Table | Tenant-owned | Notes |
|---|---|---|
| `organizations` | root | tenant root |
| `users` | no (global) | email (unique), password hash; nothing org-specific |
| `memberships` | yes | user ↔ org; `role` enum, `status` (active/deactivated); unique (org, user) |
| `departments` | yes | name unique per org, case-insensitive (`UNIQUE (organization_id, lower(name))`) |
| `department_members` | yes | membership ↔ department (N:M); PK (department_id, membership_id); composite FKs to both parents |
| `requests` | yes | department, requester, assignee?, status, priority, title, description; `assigned_at`/`started_at` (first occurrence), `completed_at`, `cancelled_at`, each CHECKed against status. Composite FKs to department/requester/assignee |
| `comments` | yes | request, author, body |
| `request_events` | yes | append-only (DB trigger rejects UPDATE/DELETE); typed `from_status`/`to_status`, JSONB `data`; `created_at = clock_timestamp()` so events in one transaction still order correctly |
| `comments` | yes | request, author, body; immutable in V1; index `(organization_id, request_id, created_at)` |
| `auth_sessions` | no | hashed session token, user, expiry (see authentication.md) |
| `login_attempts` | no | email, ip, succeeded, created_at; indexes `(email, created_at)`, `(ip, created_at)` for throttling windows; 30-day retention |

Deferred: Task, Invitation, Location, Category, per-org request numbers.

## Relationships
```
User 1──N Membership N──1 Organization
Organization 1──N Department
Membership N──M Department        (department_members)
Organization/Department 1──N Request
Membership 1──N Request (requester)   Request N──0..1 Membership (assignee)
Request 1──N Comment
Request 1──N RequestEvent
```

## Rules
- Every tenant-owned table carries `organization_id` directly.
- Composite FKs keep children in their tenant, e.g. `(organization_id, department_id) → departments(organization_id, id)`.
- No hard deletes in V1; FKs use `ON DELETE RESTRICT`.
- UUID primary keys, generated in Python (`uuid4`). Not an authorization mechanism.
- Constraint names follow a naming convention (`app/base.py`) so migrations can reference them.
- Enum-like columns: `VARCHAR(32)` + one named CHECK (ADR-009).
- Emails stored lowercase; `CHECK (email = lower(email))` + `UNIQUE(email)`.
- Timestamps: `timestamptz`, server-side `now()`, fetched eagerly (async sessions can't lazy-load).
- Indexes only for known query patterns. Postgres does **not** index FK columns automatically.
  - `memberships.user_id`: "which orgs is this user in?" + RESTRICT check on user delete.
  - `(organization_id, user_id)` unique already serves org-first lookups.
  - `(organization_id, id)` unique on memberships/departments: required targets for composite FKs.
  - `department_members (organization_id, membership_id)`: "which departments is this member in?"
  - `requests (organization_id, created_at DESC, id DESC)`: default list + keyset pagination. EXPLAIN shows an Index Only Scan with the cursor comparison in the Index Cond and no Sort.
  - `requests (organization_id, requester_membership_id, created_at DESC)`: a member's own requests.
  - `request_events (organization_id, request_id, created_at)`: one request's timeline.

## Migrations
- Autogenerate is a draft: always read it before applying. It can't tell rename from drop+add.
- Migrations use plain column types (`sa.String`), not app enums, so they stay frozen snapshots.
- `tests/test_migrations.py` fails if models change without a migration.
- Never edit a migration that has been applied anywhere shared.
- Autogenerate doesn't order *constraints on existing tables* before new FKs that need them. Check the order.
- Autogenerate does **not** detect CHECK constraints added to existing tables, and `alembic check` won't flag them missing. Write them by hand.
- Adding a constraint to a table with data: **backfill first**, then add the constraint (see the lifecycle-timestamps migration).

## Request lifecycle
```
OPEN ──assign/claim──► ASSIGNED ──start──► IN_PROGRESS ──complete──► COMPLETED
  ▲ ◄──── unassign ───── │ ▲ reassign
  └── cancel from any non-terminal ─────────────────────────────► CANCELLED
```
- Terminal: COMPLETED, CANCELLED. Deferred: reopen, ON_HOLD.
- CHECK constraint: `OPEN` ⇒ no assignee; `ASSIGNED | IN_PROGRESS | COMPLETED` ⇒ assignee required.
- All transitions go through one service function + transition table.
- Row update + `RequestEvent` in one transaction.
- Concurrent transitions: compare-and-set on (status, assignee) → 409 on conflict (ADR-014).
