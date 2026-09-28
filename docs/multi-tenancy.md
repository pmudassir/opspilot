# Multi-tenancy

## Model
Shared database, shared schema, `organization_id` on every tenant-owned table.

Alternatives considered:
- Schema-per-tenant: stronger isolation, painful migrations at N tenants.
- Database-per-tenant: strongest isolation, heavy ops; for compliance/enterprise needs.

## Request flow
1. **Authenticate**: session cookie → user.
2. **Tenant context**: `org_id` from URL path `/orgs/{org_id}/…`; caller must have an **active** membership, else 404. Produces `TenantContext(user, membership, org)`.
3. **Permission**: role → permission map in code.
4. **Object check**: every lookup is `WHERE id = :id AND organization_id = :org_id`. Other tenant's object → **404, not 403**.

## Implementation
- `app/tenancy.py`: `get_tenant_context` (steps 1–2) and `authorized(Permission.X)` (step 3).
- `app/permissions.py`: the role → permission map. Routes ask for permissions, never roles.
- Services take `organization_id` as a required argument and filter every query by it (step 4).
- Deactivation takes effect on the next request: membership status is read on every request.

## Endpoints (`/api/v1/orgs/{org_id}`)
| Method | Path | Permission |
|---|---|---|
| GET | `` | organization:read |
| GET | `/members` | members:read |
| POST | `/members` | members:manage. Creates a **new** account only; existing emails → 409 (consent, no password control over others' accounts) |
| PATCH | `/members/{membership_id}` | members:manage. Can't remove the last active admin (409) |
| GET | `/departments` | departments:read |
| POST | `/departments` | departments:manage. Names unique per org, case-insensitive |
| GET | `/departments/{department_id}/members` | members:read |
| PUT / DELETE | `/departments/{department_id}/members/{membership_id}` | departments:manage. Idempotent |
| POST | `/requests` | requests:create. `department_id` in the body must belong to the org (else 422) |
| GET | `/requests` | requests:read. Filters: `status` (repeatable), `department_id`, `priority`; keyset pagination (`limit` ≤ 100, `cursor`) |
| GET | `/requests/{request_id}` | requests:read |
| GET | `/requests/{request_id}/events` | requests:read |
| POST | `/requests/{request_id}/assign` `{assignee_membership_id}` | requests:assign (manager, admin). Assignee: active staff in the request's department (else 422). Same assignee again = no-op |
| POST | `/requests/{request_id}/claim` | requests:claim (staff), only OPEN requests in the caller's own departments |
| POST | `/requests/{request_id}/unassign` | requests:assign |
| POST | `/requests/{request_id}/start`, `/complete` | requests:work if assignee; requests:work_any (manager, admin) for anyone's |
| POST | `/requests/{request_id}/cancel` | requests:cancel_any (manager, admin), or the requester while OPEN |
| GET / POST | `/requests/{request_id}/comments` | requests:read / requests:comment, on requests the caller can see |

**Request visibility:** members see only requests they created (`requests:read_all` is staff-only). It's applied as a SQL filter, and invisible requests return 404, the same as nonexistent ones.

## Permissions (V1)
| Action | Member | Agent | Manager | Admin |
|---|---|---|---|---|
| Create request | ✓ | ✓ | ✓ | ✓ |
| View requests | own only | all in org | all in org | all in org |
| Comment | on visible requests | ✓ | ✓ | ✓ |
| Assign / reassign / unassign | — | self-claim in own dept | ✓ | ✓ |
| Start / complete | — | if assignee | ✓ | ✓ |
| Cancel | own, while OPEN | — | ✓ | ✓ |
| Manage departments & members | — | — | — | ✓ |

## Main failure mode & defenses
Failure: one query forgets the org filter → cross-tenant leak.
1. `TenantContext` is the only source of org ID; client-supplied tenant IDs in bodies are never trusted.
2. Tenant service/query functions require `org_id`; no unscoped helpers.
3. Composite FKs block cross-tenant links in the DB.
4. Cross-tenant test suite: Org B user hits Org A IDs on every endpoint → expects 404.
5. Later: Postgres Row-Level Security as a safety net (deferred: interacts with pooling/session variables).

## Concurrency: "at least one active admin"
Two admins demoting each other concurrently is **write skew**: each transaction checks a different row, so neither conflicts at the row level, and both commit → zero admins. `update_member` takes `SELECT … FOR UPDATE` on the organization row first, serializing admin changes per org. `test_concurrent_mutual_demotion_keeps_one_admin` forces the interleaving deterministically and fails if the lock is removed.

## Concurrency: lifecycle transitions (lost update)
Every transition loads the request, authorizes against that snapshot, then runs a compare-and-set:
`UPDATE requests … WHERE id = :id AND status = :seen AND assignee IS NOT DISTINCT FROM :seen_assignee`.
If another transition committed in between, 0 rows match → 409 "changed by someone else". Tests force both
requests past their checks before either writes (a rendezvous around `_compare_and_set`), so they fail if the guard is removed.
