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
