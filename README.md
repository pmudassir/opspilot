# OpsPilot

Multi-tenant operations platform. See `docs/` for architecture and decisions.

## Backend — local setup

Requires: Docker, [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d --wait        # Postgres 17 (dev DB + opspilot_test)
cd backend
cp .env.example .env               # first time only
uv sync
uv run alembic upgrade head        # create/upgrade the dev DB schema (repeat after pulling new migrations)
uv run pytest                      # tests run against opspilot_test (migrated automatically)
uv run python -m scripts.seed_demo # optional: demo hotel, one login per role (safe to re-run)
uv run uvicorn app.main:app --reload
curl localhost:8000/health         # {"status":"ok","database":"ok"}
```

Maintenance: `uv run python -m scripts.cleanup_expired` removes expired sessions and old login attempts (run daily).

## Frontend — local setup

Requires Node 24+. The backend must be running on port 8000.

```bash
cd frontend
npm install
npm run dev                        # http://localhost:3000 (proxies /api to :8000)
npm run gen:api                    # after backend API changes: regenerate TS types
npm run typecheck && npm run lint && npm test
npx playwright install chromium      # first time only (skip if already cached)
npm run test:e2e                     # own servers on :3001/:8001 + opspilot_e2e DB; dev servers untouched
```

## CI

`.github/workflows/ci.yml` runs on every push to `main` and every pull request:
`backend` (Postgres service, `uv sync --frozen`, Ruff, pytest incl. migration-drift and OpenAPI-snapshot checks),
`frontend` (`npm ci`, typecheck, lint, Vitest, build) and `e2e` (Playwright against its own servers and database;
the report is uploaded as an artifact on failure).
