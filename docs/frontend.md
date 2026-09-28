# Frontend

`frontend/`: Next.js 16 (App Router), TypeScript, Tailwind CSS v4, TanStack Query, openapi-fetch.

## Principles
- **Thin client.** The API enforces every rule. The UI may hide controls for convenience; it never decides access.
- **Same origin.** `next.config.ts` rewrites `/api/*` to FastAPI (`API_ORIGIN`, default `http://localhost:8000`). The session cookie is first-party; no CORS. The backend's Origin check still applies (`ALLOWED_ORIGINS` includes `http://localhost:3000`).
- **Generated types.** `npm run gen:api` exports FastAPI's OpenAPI schema to `src/lib/api/openapi.json` and generates `src/lib/api/schema.ts`. The backend test `test_openapi_snapshot.py` fails if the snapshot is stale.

## Data flow
- `src/lib/api/client.ts`: typed `api` client, `unwrap()` → data or `ApiError(status, detail)`, `errorMessage()`, `fieldErrors` for FastAPI 422s.
- Server state lives in TanStack Query. `me` (`src/lib/auth.ts`) is the session: `useMe()`, `useLogin()`, `useSignup()`, `useLogout()`.
- Login/signup clear the whole query cache first, so no data from a previous user survives on a shared browser.
- **Session expiry:** any 401 from another query/mutation invalidates `me`; `AppShell` sees `me` → 401 and redirects to `/login?next=…`. The `me` query is excluded from that trigger (it caused an infinite refetch loop: 1,193 requests in 2.5 s).
- `safeNextPath()` accepts only relative paths (`/x`, not `//evil` or `https://…`) to prevent an open redirect after login.
- Retries: only network errors and 5xx (a 4xx can't succeed on retry).

## Routes
| Route | Notes |
|---|---|
| `/` | Redirects to the first organization, or `/login` |
| `/login`, `/signup` | Public. `useSearchParams` wrapped in `<Suspense>` (Next.js requirement) |
| `/orgs/[orgId]/*` | `AppShell`: requires session + membership of `orgId`; provides `useCurrentOrg()` (role for UI only) |

## Checks
`npm run typecheck` (runs `next typegen` first so route types exist), `npm run lint`, `npm run build`.
