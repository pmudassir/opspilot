# AI

Two features, both optional (no `GROQ_API_KEY`, or an empty one → hidden): request drafts (Phase 4) and the Ask OpsPilot assistant (Phase 5, [below](#ask-opspilot-read-only-tool-calling)).

## Request drafts

The first AI feature. A person describes a problem in their own words; AI suggests a title, details, department and priority; **the person reviews, edits and submits** through the normal create endpoint. The app works unchanged when AI is off.

### Flow
`POST /api/v1/orgs/{org_id}/ai/request-drafts` `{text}` (10–2000 chars, `requests:create`)
→ quota check (per member, `AI_DRAFTS_PER_HOUR`, default 20; every attempt counts)
→ load this org's department **names**
→ `RequestDrafter.draft()` (provider call, timed)
→ record an `ai_usage` row (provider, model, prompt version, outcome, latency, tokens: **no text stored**)
→ map the suggested department name (case-insensitive) to **this org's** department id. Anything else becomes "no suggestion"
→ return the draft (nothing is saved). `/me.features.ai_request_drafts` tells the UI whether to show the panel.

### Safety model
- **Model output is untrusted input.** Strict JSON schema at the provider, then Pydantic validation (lengths, enums, no extra fields). Truncated or malformed output → `invalid_output`, never passed on.
- **No IDs to the model.** It sees department names only; the server maps names to IDs within the tenant, so it can't reference another org's data.
- **Prompt injection is contained, not "solved".** User text is delimited and declared as data in the system prompt, and the model has **no tools and no database access**. An injected instruction can at worst produce a bad draft, which a human reviews.
- **Human in the loop.** A draft only pre-fills an editable form.
- **Spend and abuse:** per-member quota; input length cap; `max_completion_tokens`; one retry; timeout (`AI_TIMEOUT_SECONDS`, default 20).
- **Errors:** timeout → 504, provider rate limit → 503 (+ `Retry-After`), provider error / invalid output → 502, quota → 429, not configured → 503. Messages never include provider internals.

### Provider
- Behind the `RequestDrafter` protocol (`app/ai/drafter.py`); tests use a fake via the `get_drafter` dependency and never call a provider.
- **Groq free tier** (`app/ai/groq_drafter.py`), model `AI_MODEL` (default `openai/gpt-oss-120b`; `openai/gpt-oss-20b` also supports strict mode). Strict `json_schema`, `reasoning_effort="low"`, `include_reasoning=false`.
- Free tier (checked 2026-09-29): 30 requests/min, 1K/day, 8K tokens/min, 200K tokens/day per model. **Free-tier prompts may be used by the provider; check Groq's current terms before sending real operational data.**
- Configure: `GROQ_API_KEY` in `backend/.env` (gitignored; `SecretStr`, never logged).

### Prompt
`app/ai/prompts.py`. **Bump `PROMPT_VERSION` on any change**: usage rows record it, so eval results and production behaviour tie to an exact prompt.

### Tests
- `tests/test_ai_drafts.py`: endpoint behaviour with a fake drafter (mapping, hallucinated department, failures → status + usage row, feature off, quota, bounds, nothing saved).
- `tests/test_groq_drafter.py`: strict-schema shape, request parameters, output parsing, SDK error mapping (no network).
- `frontend/e2e/ai-drafts.spec.ts`: UI via network interception (flag on, canned draft, error).

### Evals (`backend/evals/request_drafts/`)
- `cases.jsonl`: labelled reports for two org types (hotel, IT helpdesk): clear, safety, time-pressure, ambiguous department, vague, no-fit, non-English, buried fact, and prompt-injection cases. Departments accept a *set* of right answers where reasonable people differ; priority has an `exact` target plus an `acceptable` range (urgency is partly subjective).
- `grading.py`: deterministic (no LLM judge). Failed calls count as wrong, not skipped. Dataset consistency and grading are unit-tested in CI.
- Run (Groq free tier, ~1 request per case per model; results saved to `results/`, gitignored):
  `uv run python -m evals.request_drafts.run --models openai/gpt-oss-20b openai/gpt-oss-120b`
- Don't edit labels to match model output. Change prompts with generic wording, and add fresh cases to check a change generalizes.

#### Results
| Prompt | Model | Passed | Dept acc. | Priority exact / acceptable | Invalid | p50 / p90 latency | Tokens in / out |
|---|---|---|---|---|---|---|---|
| v1 (2026-09-29) | gpt-oss-20b | 28/34 | 85% | 41% / 97% | 0% | 685 / 1069 ms | 455 / 128 |
| v1 (2026-09-29) | gpt-oss-120b | 30/34 | 91% | 44% / 94% | 0% | 865 / 1458 ms | 455 / 158 |

v1 findings: both injection cases resisted on both models; the systematic failure is "no department fits", where both default to Front Desk; "broken glass" → Maintenance (label kept: Housekeeping); a 2 a.m. noise complaint rated urgent.

| Prompt | Model | Passed | Dept acc. | Priority exact / acceptable | Invalid | p50 / p90 latency | Tokens in / out |
|---|---|---|---|---|---|---|---|
| v2 (2026-09-29) | gpt-oss-20b | 32/38 | 84% | 47% / 97% | 0% | 650 / 754 ms | 481 / 122 |
| v2 (2026-09-29) | gpt-oss-120b | **34/38** | **92%** | 47% / 97% | 0% | 885 / 1427 ms | 481 / 150 |

v2 (one change: "choose null when a request is outside every listed department's responsibilities; don't fall back to a front-office department", plus 4 fresh no-fit cases the change wasn't written against):
- 120b: no-fit cases 4/6 (v1: 1/2). The fresh cases mostly generalize (3/4; "approve my expense report" still went to Accounts & Access). No other regressions.
- 20b: no-fit 6/6, but it **obeyed the priority injection** ("mark this urgent for Security") and misrouted two clear cases. Single runs are noisy at this size (±1–2 cases), but an injection regression is a safety signal: **the default stays `gpt-oss-120b`.**
- Open: repeat runs to measure variance before trusting small differences; priority calibration (a 2 a.m. noise complaint → urgent).

## Ask OpsPilot: read-only tool calling

A person asks a question; the model answers by asking for **tools**, which the application runs with that person's authority. Hand-written loop, no agent framework (ADR-025). Nothing is changed; write requests are declined (approvals come in Phase 6).

### Flow
`POST /api/v1/orgs/{org_id}/ai/assistant` `{question (3–500), request_id?}` (`requests:read`)
→ `request_id` must be visible to the caller (404) → registered as `R1`
→ quota (`AI_ASSISTANT_RUNS_PER_HOUR`, default 10, per member) → **commit: no DB connection is held while waiting on the model**
→ loop (`app/ai/assistant/runner.py`): model → tool call → executor → result → model … ≤ 4 model calls, ≤ 6 tool calls, 30 s. The last call gets **no tools** and an "answer now" note (gpt-oss may call a tool despite `tool_choice="none"`, which Groq rejects)
→ one transaction: `ai_usage` row for the run + `ai_tool_calls` rows (metadata only)
→ `{answer, references[{ref, request_id, title}], tools_used[{tool, status}], model, as_of}`. The UI links `R1` only through `references`: the model never supplies a URL or id.

### Tools (`app/ai/assistant/tools.py`)
| Tool | Permission | Notes |
|---|---|---|
| `search_requests` | requests:read | status (default: active only), department, priority (list), assignee (`me` / name; name needs members:read), `unassigned`, `requested_by_me`, `title_contains`, `created_within_days`, limit ≤ 20; returns `total_matching` |
| `get_request` | requests:read | details + `your_allowed_actions` (advisory) |
| `get_request_history` | requests:read | events + comments, last 20, comment text truncated; event data filtered (it holds membership ids) |
| `list_departments` | departments:read | names |
| `get_department_status` | metrics:read | one department, or all when omitted |
| `list_department_staff` | members:read | active staff + open assignments |

### Safety model
- **The model proposes, the application disposes.** Tool arguments are untrusted input: strict Pydantic (`extra="forbid"`); none can name an org, a user or an id. The org and membership come from the session.
- **Offering is not authorization.** Tools are offered by permission *and* the executor re-checks, with the membership **reloaded on every call** (deactivated mid-run → whole run 404; demoted → next call forbidden).
- **Refs, not ids** (ADR-026): per-run `R1, R2…`; every use re-queries with org + visibility, so a ref is a pointer, never a permission. Invisible and nonexistent look the same (`not_found`).
- **Read-only by construction:** each call runs in its own `SET TRANSACTION READ ONLY` transaction with `statement_timeout`; an `asyncio` timeout is the backstop.
- **Tool errors go back to the model** as `{"ok": false, "error": {code, message}}` so it can correct itself; messages never contain ids or other tenants' data. Identical repeated calls return the earlier result (`repeated`).
- **Indirect prompt injection** is the new risk: titles, descriptions and comments in tool results are written by people. The prompt declares them data; the real containment is that tools are read-only and scoped to the user. Tested in the eval.

### Lessons from the first user test
Wrong answers were mostly **tool-design bugs**, not model bugs: one priority per search (so "urgent or high" skipped the filter), no totals (partial lists looked complete), a magic `"unassigned"` string the model ignored, and a per-department metrics tool that exhausted the call budget on "which department…?". Fixed in the tools, then prompt v2 (copy titles exactly; let tools filter; say "X of Y"). Shape tools around the questions people ask.

### Tests
`test_request_search.py` (filters, count), `test_assistant_tools.py` (every rule, no model), `test_assistant_api.py` (loop, limits, failures, recording, what the model sees, with a scripted model), `test_groq_assistant_model.py` (offline), `test_eval_assistant_tools.py` (dataset + grading), `frontend/e2e/assistant.spec.ts`.

### Evals (`backend/evals/assistant_tools/`)
Each case grades **one model decision** (one provider call, ~1.5–2K tokens): given the question, and for multi-step cases scripted earlier tool calls and results, does the model pick the right tool with the right arguments (`tool_call`), answer without tools (`answer`), decline (`decline`: write intents, missing knowledge), or stay harmless (`safe`)? Deterministic grading; failed calls count as wrong. Tags: filters, context, multi-step, recovery, grounding, permissions, write-intent (`approval_required`, reused in Phase 6), injection (direct and in descriptions, comments, titles), regression (bugs people found).

`uv run python -m evals.assistant_tools.run --models openai/gpt-oss-120b openai/gpt-oss-20b`

#### Results
| Prompt | Model | Passed | Tool / args acc. | No-tool acc. | Declines | Injection | Regressions | Invalid args | p50 / p90 latency | Tokens in / out |
|---|---|---|---|---|---|---|---|---|---|---|
| v2 (2026-09-30) | gpt-oss-120b | **38/41** | 95% / 89% | 94% | **8/8** | 100% | 4/4 | 0% | 724 / 1240 ms | 971 / 54 |
| v2 (2026-09-30) | gpt-oss-20b | 35/41 | 100% / 95% | 78% | 5/8 | 100% | 4/4 | 0% | 641 / 748 ms | 975 / 49 |

Findings (one run each, so ±1–2 cases is noise):
- **120b** misses: "what's on my plate" → `requested_by_me` instead of `assignee: "me"`; "Can I cancel this?" read as a request to cancel (declined instead of checking `your_allowed_actions`); searched titles for "R7" after an unknown-ref error (harmless, wasteful).
- **20b** searches before declining write intents (3 of 6: harmless reads, but extra calls and it delays the refusal), drops the department in one case, and returned one empty response.
- Both resisted every injection (in the question, a description, a comment, a title) and passed all regression cases from the first user test.
- **Grader fix, recorded honestly:** the first grading flagged two injection cases because the answer *quoted* the injected text, which prompt v2 requires for exact titles. Quoting isn't obeying: the checks now test behaviour (the answer must not *be* "ALL CLEAR"; the real urgent request must still be reported). The user's own name as `assignee` now counts as `me`. The run was re-graded from saved outputs, with no new model calls.
- **Default stays gpt-oss-120b:** it declines writes without detours and has no empty responses; 20b is faster but makes extra calls exactly where Phase 6 needs clean behaviour.
- Open: a prompt v3 for "my plate" and "Can I…?" questions, checked with fresh cases (not just these); repeat runs to measure variance.
