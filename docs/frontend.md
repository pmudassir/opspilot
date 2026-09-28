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
| `/orgs/[orgId]/requests` | List: filters in the URL, "Load more" via cursor (`useInfiniteQuery`), loading/empty/filtered-empty/error states |
| `/orgs/[orgId]/requests/new` | Create form (department required, priority default normal); 422s shown per field; opens the new request |
| `/orgs/[orgId]/members` | Needs `members:read`. Admins (`members:manage`): add member (new accounts only; 409 for existing emails), inline role change, two-step deactivate, reactivate. The API's "keep one active admin" 409 is shown as-is |
| `/orgs/[orgId]/departments` | Everyone sees names; `members:read` shows staff; `departments:manage` creates departments and adds/removes staff (idempotent PUT/DELETE) |
| `/orgs/[orgId]/requests/[requestId]` | Detail: description, activity timeline (events + comments), comment form, actions panel, details/timestamps; 404 → "doesn't exist or no access" |

## Permissions come from the API
- `/me` returns `permissions` per membership, straight from the backend's role → permission map. `useCurrentOrg().can("members:manage")` decides what to *show* (nav items, forms, inline controls). Never compare role names in the UI.
- Showing ≠ allowing: a member typing `/members` gets the API's 403 → "You don't have access".

## Actions come from the API
- Every `RequestOut` carries `allowed_actions`, computed by the backend's lifecycle rules for the *caller* (`app/requests/lifecycle.py`). The actions panel renders only those; no role logic in the frontend.
- A stale page can still offer an action that's no longer valid (someone acted first). The API answers 409/403; the UI shows the message and refetches the request, so the buttons update to what's valid now.
- Assign uses an inline picker of active staff in the request's department (`GET /departments/{id}/members`, available to managers/admins, who are the only ones offered "Assign"). Cancel has an inline two-step confirmation.

## Request list details
- **Filters live in the URL** (`?status=open&status=assigned&department_id=…&priority=urgent`): shareable, reload-safe. `parseFilters()` treats the URL as untrusted input (unknown statuses, non-UUID department ids and bad priorities are dropped).
- Filter changes use `router.push` so **Back undoes a filter**. (`router.replace` overwrote history and Back left the page. Caught by a browser check.)
- Query keys include org + filters: `["requests", orgId, "list", filters]`. Creating a request invalidates `["requests", orgId]`, which refreshes every filtered view of that org.
- Label/style maps are `Record<RequestStatus, …>` over the generated types: a new backend status fails the frontend build until handled.

## Checks
`npm run typecheck` (runs `next typegen` first so route types exist), `npm run lint`, `npm test`, `npm run test:e2e` (Vitest: pure logic such as URL filters, the open-redirect guard, time formatting), `npm run build`.

## End-to-end tests (`frontend/e2e/`, Playwright)
- `npm run test:e2e` starts its **own** backend (:8001) and production frontend (:3001, built into `.next-e2e`) against `opspilot_e2e`, which `backend/scripts/reset_e2e_database.py` creates/migrates/empties first (it refuses any DB not named `*_e2e`). Dev servers and dev data are untouched; ports 3001/8001 must be free.
- Setup through the API (`e2e/support.ts`: `createOrg`, `addMember`, `createRequest`, `act`, `pageAs`), behaviour through the UI. Every test creates its own org, so tests run in parallel.
- No retries: flakes are bugs. Match our error box with `errorBox(page)`, not any `role="alert"`.
- Coverage: signup; login/logout; deep link through login (keeps the query string); open-redirect guard; session check runs once; filters in URL + Back; load more; junk URL params; role-based navigation; stale action → 409 → refresh; deactivation; last-admin guard; and one full UI journey from signup to a completed request.
- Found by this suite: the post-login redirect dropped the deep link's query string (`usePathname` excludes it), and sign-out raced the app shell's "session expired" redirect (clearing the cache in place). Sign-out now does a full page load, which also guarantees none of the previous user's data survives.

## Lessons
- `@types/node` must match the Node runtime (24). The scaffold's `^20` blocked Vitest 5; fixed the version rather than forcing with `--legacy-peer-deps`.
- Next.js renders a hidden `role="alert"` route announcer. Browser tests must target our error box, not any alert.
- `@playwright/test` is pinned to 1.60.0 to match the locally cached Chromium build.
- When checking UI locally, make sure *your* server is the one answering: a dev server already on :3000/:8000 silently took the ports. Use other ports (`API_ORIGIN`, `ALLOWED_ORIGINS`) for scripted checks.
- The e2e build writes to `.next-e2e` and Next.js adds that folder's type paths to `tsconfig.json` (committed, so runs don't dirty the tree). It also points the gitignored `next-env.d.ts` there; `npm run typecheck` or `next dev` regenerates it.
- Don't run `next build` in the same folder as a running `next dev`: it left the dev server returning 404 for a newly added route (a fresh dev server served it fine). Restarting `npm run dev` fixes it. Build from a separate copy instead.
- Playwright `getByRole(..., { name })` matches a **case-insensitive substring** by default: waiting for heading "IT" matched "Facil*it*ies". That made a script type into a form mid-request, so it looked like a stuck button. Use `exact: true` for short names.
- In browser checks, use auto-retrying assertions (`expect(...).toHaveValue(...)`) instead of reading state right after an action. The UI updates in more than one render.
