# FastAPI & async — lessons

- **CPU-heavy work blocks the event loop.** argon2 hashing (~50 ms CPU) inside `async def` would stall every concurrent request. Run it with `run_in_threadpool`.
- **Set cookies on an injected `Response`** when returning a model; FastAPI merges the headers. Headers set this way are dropped if you raise `HTTPException`.
- **Dependencies are the seams for testing.** `app.dependency_overrides[get_session] = ...` simulated a database outage without stopping Postgres.
- **A test that can't fail proves nothing.** Asserting on a freshly created client's cookies was always true. Assert on the real response instead.
