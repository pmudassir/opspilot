# OpsPilot

Multi-tenant operations platform. See `docs/` for architecture and decisions.

## Backend — local setup

Requires: Docker, [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d --wait        # Postgres 17 (dev DB + opspilot_test)
cd backend
cp .env.example .env               # first time only
uv sync
uv run pytest                      # tests run against opspilot_test
uv run uvicorn app.main:app --reload
curl localhost:8000/health         # {"status":"ok","database":"ok"}
```
