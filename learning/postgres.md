# PostgreSQL & SQLAlchemy — lessons

## Bugs caught
- **Autogenerate duplicated CHECK constraints** for `Enum(native_enum=False, create_constraint=True)`:
  explicit `CheckConstraint` lines *plus* the Enum type's own constraint. Fixed by hand-editing the
  migration to `sa.String(32)` + one named CHECK. Lesson: read every generated migration.

## Things that surprised
- Postgres doesn't index foreign-key columns automatically. Deleting a parent row then scans the child table.
- `onupdate=func.now()` values get expired after flush; in async that access would fail. `eager_defaults=True` fetches them via `RETURNING`.
- `now()` is the transaction start time, not the statement time.
- Alembic's `fileConfig()` disables existing loggers unless `disable_existing_loggers=False`.
