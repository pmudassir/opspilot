# Metrics

`GET /api/v1/orgs/{org_id}/metrics?days=30` (1–365; `metrics:read`, managers and admins). UI: `/orgs/[orgId]/metrics` (7/30/90 days, `?days=` in the URL).

## Definitions
| Metric | Meaning |
|---|---|
| Backlog | Requests currently `open` + `assigned` + `in_progress`. **Not** period-bound |
| Created / Completed / Cancelled | Requests whose `created_at` / `completed_at` / `cancelled_at` falls in the last N days |
| Time to assign | `created_at` → **first** assignment (`assigned_at`), for requests created in the period |
| Time to complete | `created_at` → `completed_at`, for requests completed in the period |

Reported as **median** ("typical") and **p90** (the slowest 10% take longer), never the mean. One request left open for a month would drag an average away from what a typical request experiences; the median shows the typical case and p90 the slow tail.

## Implementation
- One grouped SQL query per department plus one ungrouped query for org totals (`app/metrics/service.py`). Percentiles can't be combined from per-department results, so totals are computed separately.
- `percentile_cont(f) WITHIN GROUP (ORDER BY CASE WHEN <in scope> THEN <hours> END)`: rows out of scope become NULL, which the percentile ignores.
- `LEFT JOIN` from departments, so departments without requests appear with zeros and "—".
- Both queries filter by `organization_id`. A test with another org's data proves nothing leaks (removing the filter changed the totals 6 → 9).

## Known limits
- Computed on every request: fine at our scale. At large volume, pre-aggregate (materialized view or daily rollups).
- Reassignment and reopening aren't reflected in "time to assign" (first assignment only); the event log has the full history.
- Seeded demo data shows "< 1 min" everywhere: the seed performs all actions instantly, and history events can't be backdated (append-only).
