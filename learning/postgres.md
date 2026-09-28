# PostgreSQL & SQLAlchemy — lessons

## Bugs caught
- **Autogenerate duplicated CHECK constraints** for `Enum(native_enum=False, create_constraint=True)`:
  explicit `CheckConstraint` lines *plus* the Enum type's own constraint. Fixed by hand-editing the
  migration to `sa.String(32)` + one named CHECK. Lesson: read every generated migration.

- **`func.lower("name")` lowers the string literal `'name'`, not the column.** The "unique department name" index would have allowed one department per org. Caught by reading autogenerate's log line (`on ('organization_id',)`). Use `text("lower(name)")` in `__table_args__`.
- **Autogenerate ordered a UNIQUE constraint after the composite FK that needed it**, and dropped it first on downgrade. Reordered by hand; verified with upgrade → downgrade → upgrade.

## Concurrency
- **Lost update** (Q5): two writers, same row. Fix: conditional `UPDATE … WHERE status = expected`.
- **Write skew:** two writers each *check* a set of rows and each *write* a different row, so there's no row conflict and both commit, breaking an invariant ("≥ 1 admin"). Fix: lock a shared row (`SELECT … FOR UPDATE` on the org) or use SERIALIZABLE isolation.
- Under READ COMMITTED, each statement sees data committed before *it* started, so a query after acquiring a lock sees the other transaction's commit.
- **Concurrency tests must force the interleaving.** `asyncio.gather` alone passed with the lock removed, because one request finished before the other started. A commit rendezvous made the test fail 3/3 without the lock.

- **Lost update vs write skew, solved differently.** Same row → guarded UPDATE (compare-and-set); the second writer blocks on the row lock, re-checks its WHERE against the committed row, and matches 0 rows. Different rows → lock a shared row.
- **`IS NOT DISTINCT FROM`**: `NULL = NULL` is NULL (not true), so "assignee unchanged" needs the null-safe comparison.

## Pagination & ordering
- `now()` is the transaction start time: rows inserted in one transaction share it. Use `clock_timestamp()` when order *within* a transaction matters (event timelines).
- Keyset pagination: `WHERE (created_at, id) < (:c, :i) ORDER BY created_at DESC, id DESC LIMIT n+1`. Postgres row comparison matches a composite index; the extra row tells you whether a next page exists.
- Verify index fit with `EXPLAIN`. On tiny tables Postgres prefers a seq scan, so use `SET enable_seqscan = off` to see whether an index *can* serve the query.

## Things that surprised
- Postgres doesn't index foreign-key columns automatically. Deleting a parent row then scans the child table.
- `onupdate=func.now()` values get expired after flush; in async that access would fail. `eager_defaults=True` fetches them via `RETURNING`.
- `now()` is the transaction start time, not the statement time.
- Alembic's `fileConfig()` disables existing loggers unless `disable_existing_loggers=False`.
