# AI: request drafts

The first AI feature. A person describes a problem in their own words; AI suggests a title, details, department and priority; **the person reviews, edits and submits** through the normal create endpoint. The app works unchanged when AI is off.

## Flow
`POST /api/v1/orgs/{org_id}/ai/request-drafts` `{text}` (10–2000 chars, `requests:create`)
→ quota check (per member, `AI_DRAFTS_PER_HOUR`, default 20; every attempt counts)
→ load this org's department **names**
→ `RequestDrafter.draft()` (provider call, timed)
→ record an `ai_usage` row (provider, model, prompt version, outcome, latency, tokens: **no text stored**)
→ map the suggested department name (case-insensitive) to **this org's** department id. Anything else becomes "no suggestion"
→ return the draft (nothing is saved). `/me.features.ai_request_drafts` tells the UI whether to show the panel.

## Safety model
- **Model output is untrusted input.** Strict JSON schema at the provider, then Pydantic validation (lengths, enums, no extra fields). Truncated or malformed output → `invalid_output`, never passed on.
- **No IDs to the model.** It sees department names only; the server maps names to IDs within the tenant, so it can't reference another org's data.
- **Prompt injection is contained, not "solved".** User text is delimited and declared as data in the system prompt, and the model has **no tools and no database access**. An injected instruction can at worst produce a bad draft, which a human reviews.
- **Human in the loop.** A draft only pre-fills an editable form.
- **Spend and abuse:** per-member quota; input length cap; `max_completion_tokens`; one retry; timeout (`AI_TIMEOUT_SECONDS`, default 20).
- **Errors:** timeout → 504, provider rate limit → 503 (+ `Retry-After`), provider error / invalid output → 502, quota → 429, not configured → 503. Messages never include provider internals.

## Provider
- Behind the `RequestDrafter` protocol (`app/ai/drafter.py`); tests use a fake via the `get_drafter` dependency and never call a provider.
- **Groq free tier** (`app/ai/groq_drafter.py`), model `AI_MODEL` (default `openai/gpt-oss-120b`; `openai/gpt-oss-20b` also supports strict mode). Strict `json_schema`, `reasoning_effort="low"`, `include_reasoning=false`.
- Free tier (checked 2026-09-29): 30 requests/min, 1K/day, 8K tokens/min, 200K tokens/day per model. **Free-tier prompts may be used by the provider; check Groq's current terms before sending real operational data.**
- Configure: `GROQ_API_KEY` in `backend/.env` (gitignored; `SecretStr`, never logged).

## Prompt
`app/ai/prompts.py`. **Bump `PROMPT_VERSION` on any change**: usage rows record it, so eval results and production behaviour tie to an exact prompt.

## Tests
- `tests/test_ai_drafts.py`: endpoint behaviour with a fake drafter (mapping, hallucinated department, failures → status + usage row, feature off, quota, bounds, nothing saved).
- `tests/test_groq_drafter.py`: strict-schema shape, request parameters, output parsing, SDK error mapping (no network).
- `frontend/e2e/ai-drafts.spec.ts`: UI via network interception (flag on, canned draft, error).

## Next: evals
A labelled dataset of realistic reports (expected department + priority) and a script measuring department accuracy, priority accuracy, invalid-output rate, latency and tokens, comparing `gpt-oss-20b` vs `gpt-oss-120b` (both free). It needs `GROQ_API_KEY`.
