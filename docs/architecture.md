# Architecture

## What V1 is
A system of record for operational requests per organization: capture → route to department → assign → lifecycle → history → (later) metrics.
Must remain fully useful with any future AI switched off.

## Shape
```
Browser
   │  httpOnly session cookie
   ▼
Next.js (App Router, TS) — UI only; /api/* rewritten to FastAPI (same-origin cookie)
   ▼
FastAPI — one modular monolith
   routers → dependencies (auth → TenantContext → permission)
           → services (business rules, lifecycle transitions, event writing)
           → SQLAlchemy 2 (async, asyncpg)
   modules: auth · organizations (members, departments) · requests (requests, comments, events)
   ▼
PostgreSQL ◄── Alembic migrations
```
Tests: pytest + HTTPX against a real Postgres test DB (not SQLite).

## Layer responsibilities
| Layer | Owns | Must not |
|---|---|---|
| Router | HTTP shape, status codes, Pydantic schemas | contain business rules |
| Dependencies | session, current user, TenantContext, permission checks | query tenant data without org_id |
| Service | business rules, transitions, transactions, events | know about HTTP |
| Models | schema + DB constraints | — |

## Out of scope for V1
AI of any kind (since added in Phase 4 as an optional layer: `docs/ai.md`), notifications, attachments, SLAs, custom workflows/roles, SSO, email invites, subtasks, recurring work, billing, guest portal, Redis/queues/workers, cloud deployment.

## Assumptions
Internal authenticated requesters only · small scale (tens of orgs, thousands of requests) · fixed roles and lifecycle for all orgs · `timestamptz` UTC · Python 3.13 + uv · PostgreSQL 17+ via Docker Compose (Postgres only).
