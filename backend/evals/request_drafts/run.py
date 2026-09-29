"""Run the request-draft eval against real models (Groq free tier: costs no money,
but uses rate-limited quota: ~1 request per case per model).

Usage (from backend/):
    uv run python -m evals.request_drafts.run --models openai/gpt-oss-20b openai/gpt-oss-120b
Writes evals/request_drafts/results/<timestamp>.json (gitignored) and prints a summary.
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.ai.drafter import DrafterError, DraftFailure
from app.ai.groq_drafter import GroqDrafter
from app.ai.prompts import PROMPT_VERSION
from app.config import get_settings
from evals.request_drafts.grading import CaseResult, grade, load_cases, summarize

RESULTS_DIR = Path(__file__).with_name("results")
PACING_SECONDS = 4.5  # stays well under the free tier's 8K tokens/min per model
MAX_RATE_LIMIT_RETRIES = 3


async def run_case(drafter: GroqDrafter, case) -> CaseResult:  # noqa: ANN001
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        started = time.perf_counter()
        try:
            draft = await drafter.draft(text=case.text, departments=case.org_departments)
            return grade(case, draft, None, round((time.perf_counter() - started) * 1000))
        except DrafterError as exc:
            latency = round((time.perf_counter() - started) * 1000)
            if exc.failure == DraftFailure.RATE_LIMITED and attempt < MAX_RATE_LIMIT_RETRIES:
                wait = (exc.retry_after_seconds or 10) + 1
                print(f"  rate limited, waiting {wait}s", file=sys.stderr)
                await asyncio.sleep(wait)
                continue
            return grade(case, None, exc.failure, latency)
    raise AssertionError("unreachable")


async def main(models: list[str], only: list[str] | None) -> None:
    settings = get_settings()
    if settings.groq_api_key is None:
        sys.exit("GROQ_API_KEY is not set (backend/.env)")
    cases = [c for c in load_cases() if not only or c.id in only]
    drafters = {
        m: GroqDrafter(api_key=settings.groq_api_key.get_secret_value(), model=m, timeout_seconds=30)
        for m in models
    }
    results: dict[str, list[CaseResult]] = {m: [] for m in models}
    print(f"{len(cases)} cases × {len(models)} models, prompt {PROMPT_VERSION}", file=sys.stderr)
    for index, case in enumerate(cases, 1):
        for model, drafter in drafters.items():  # alternate models: each has its own limits
            result = await run_case(drafter, case)
            results[model].append(result)
            mark = "PASS" if result.passed else f"FAIL ({result.failure or 'graded'})"
            print(f"[{index:2}/{len(cases)}] {model:<22} {case.id:<30} {mark}", file=sys.stderr)
            await asyncio.sleep(PACING_SECONDS / len(models))

    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "prompt_version": PROMPT_VERSION,
        "models": {
            m: {"summary": asdict(summarize(rs)), "results": [asdict(r) for r in rs]} for m, rs in results.items()
        },
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2))

    print(f"\nPrompt {PROMPT_VERSION}  ({len(cases)} cases)")
    header = f"{'metric':<22}" + "".join(f"{m.split('/')[-1]:>16}" for m in models)
    print(header)
    for field in ["passed", "department_accuracy", "priority_exact", "priority_acceptable", "title_ok",
                  "invalid_output_rate", "error_rate", "latency_p50_ms", "latency_p90_ms",
                  "avg_input_tokens", "avg_output_tokens"]:
        row = [getattr(summarize(results[m]), field) for m in models]
        print(f"{field:<22}" + "".join(f"{('-' if v is None else v)!s:>16}" for v in row))
    print("\nFailed cases:")
    for m in models:
        for r in results[m]:
            if not r.passed:
                why = r.failure or ", ".join(
                    k for k, ok in [("department", r.department_correct), ("priority", r.priority_acceptable), ("title", r.title_ok)] if not ok
                )
                print(f"  {m.split('/')[-1]:<14} {r.case_id:<30} {why:<22} → dept={r.department!r} prio={r.priority} title={r.title!r}")
    print(f"\nSaved {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", default=[get_settings().ai_model])
    parser.add_argument("--only", nargs="*", help="run only these case ids")
    args = parser.parse_args()
    asyncio.run(main(args.models, args.only))
