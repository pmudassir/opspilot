# FastAPI & async — lessons

- **CPU-heavy work blocks the event loop.** argon2 hashing (~50 ms CPU) inside `async def` would stall every concurrent request. Run it with `run_in_threadpool`.
- **Set cookies on an injected `Response`** when returning a model; FastAPI merges the headers. Headers set this way are dropped if you raise `HTTPException`.
- **Dependencies are the seams for testing.** `app.dependency_overrides[get_session] = ...` simulated a database outage without stopping Postgres.
- **A test that can't fail proves nothing.** Asserting on a freshly created client's cookies was always true. Assert on the real response instead.
- **FastAPI 0.141 keeps included routers nested** (`_IncludedRouter`), so walking `app.routes` misses endpoints. `app.openapi()["paths"]` is the stable public list.
- **Mutation-test security checks.** Removing the tenant filter from one lookup exposed a missing test case: IDs must each be checked individually (foreign department + own member).
- **SQLAlchemy identity map returns cached objects.** A re-SELECT after taking a lock won't refresh an object already loaded in the session unless you use `populate_existing=True`.
