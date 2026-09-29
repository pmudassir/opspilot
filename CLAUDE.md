# OpsPilot — Project Rules

Multi-tenant operations platform: organizations capture, route, assign, and track operational requests.
This is a **learning-focused** project: explain significant concepts, ask 3–5 check questions after each feature (withhold answers).

## Current phase
Phase 4: AI features (request drafts done; evals next). Phases 1–3 (backend, frontend, CI/hardening/metrics) complete. See `docs/`.

## Frontend rules
- Next.js 16 has breaking changes: read `frontend/node_modules/next/dist/docs/` before using an API.
- UI is thin: no business rules. Which actions a user may take comes from the API, never re-derived.
- API types are generated: after any backend API change run `npm run gen:api` in `frontend/`
  (backend test `test_openapi_snapshot.py` fails otherwise).
- Frontend checks: `npm run typecheck && npm run lint && npm test && npm run test:e2e` (e2e uses its own ports/DB/dist dir).
- Never `next build` in `frontend/` directly while a dev server may be running; `test:e2e` builds into `.next-e2e`.

## Hard rules
- **AI features follow docs/ai.md** (first feature: request drafts via Groq free tier):
  - LLM output is untrusted input: strict schema + Pydantic validation, like any user input.
  - A human reviews AI output before anything is saved; the model gets no tools and no DB access.
  - The model never sees or returns database IDs; the server maps names → IDs within the tenant.
  - The app must work with AI switched off (no key → feature hidden).
  - Tests never call a real provider (override `get_drafter`); bump `PROMPT_VERSION` on prompt changes.
  - Still out: RAG, embeddings, pgvector, agents, MCP, until explicitly decided.
- **No new technology without answering "what problem does this solve in OpsPilot?"** (Redis, queues, K8s, Kafka, cloud are out for now.)
- **Tenant isolation is a security boundary**:
  - Org ID comes only from the URL path, validated by the `TenantContext` dependency (active membership required).
  - Every tenant-owned table has `organization_id`; every tenant query filters on it; no unscoped helpers.
  - Cross-tenant access returns 404, never 403.
  - Every new endpoint gets a cross-tenant test.
- Authorization is backend-only. The frontend never decides access.
- State change + `RequestEvent` are written in one transaction.
- No hard deletes: cancel requests, deactivate memberships.
- Never edit an applied Alembic migration.

## Docs (keep concise, update when decisions change)
- `docs/frontend.md`, `docs/metrics.md`, `docs/ai.md`, `docs/architecture.md`, `docs/database.md`, `docs/multi-tenancy.md`, `docs/authentication.md`
- `docs/decisions.md`: short ADRs
