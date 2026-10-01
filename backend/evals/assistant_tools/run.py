"""Run the tool-calling eval against real models (Groq free tier: costs no money, but
uses rate-limited quota: one request of ~1.5-2K tokens per case per model).

Usage (from backend/):
    uv run python -m evals.assistant_tools.run --models openai/gpt-oss-20b openai/gpt-oss-120b
Writes evals/assistant_tools/results/<timestamp>.json (gitignored) and prints a summary.
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.ai.assistant.groq_model import GroqAssistantModel
from app.ai.assistant.prompts import ASSISTANT_PROMPT_VERSION
from app.ai.assistant.tools import tool_definition, tools_for
from app.ai.drafter import DrafterError, DraftFailure
from app.config import get_settings
from evals.assistant_tools.grading import (
    PERSONAS,
    Case,
    CaseResult,
    build_messages,
    grade,
    load_cases,
    summarize,
)

RESULTS_DIR = Path(__file__).with_name("results")
PACING_SECONDS = 12.0  # per model: ~2K tokens per case stays under the free tier's 8K tokens/min
MAX_RATE_LIMIT_RETRIES = 3
METRICS = [
    "passed", "tool_selection_accuracy", "argument_accuracy", "no_tool_accuracy", "decline_accuracy",
    "injection_resistance", "regression_passed", "invalid_args_rate", "error_rate",
    "latency_p50_ms", "latency_p90_ms", "avg_input_tokens", "avg_output_tokens",
]


async def run_case(model: GroqAssistantModel, case: Case) -> CaseResult:
    tools = [tool_definition(tool) for tool in tools_for(PERSONAS[case.role]["role"])]
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        started = time.perf_counter()
        try:
            turn = await model.complete(build_messages(case), tools, tool_choice="auto")
            return grade(case, turn, None, round((time.perf_counter() - started) * 1000))
        except DrafterError as exc:
            latency = round((time.perf_counter() - started) * 1000)
            if exc.failure == DraftFailure.RATE_LIMITED and attempt < MAX_RATE_LIMIT_RETRIES:
                wait = (exc.retry_after_seconds or 15) + 1
                print(f"  rate limited, waiting {wait}s", file=sys.stderr)
                await asyncio.sleep(wait)
                continue
            return grade(case, None, exc.failure, latency)
    raise AssertionError("unreachable")


def _why(result: CaseResult) -> str:
    if result.failure:
        return result.failure
    if result.kind == "tool_call":
        return "wrong tool" if not result.tool_correct else "wrong arguments"
    return "called a tool" if result.called_tool else "answer text"


async def main(models: list[str], only: list[str] | None) -> None:
    settings = get_settings()
    if settings.groq_api_key is None:
        sys.exit("GROQ_API_KEY is not set (backend/.env)")
    cases = [c for c in load_cases() if not only or c.id in only]
    clients = {
        m: GroqAssistantModel(api_key=settings.groq_api_key.get_secret_value(), model=m, timeout_seconds=30)
        for m in models
    }
    results: dict[str, list[CaseResult]] = {m: [] for m in models}
    print(f"{len(cases)} cases × {len(models)} models, prompt {ASSISTANT_PROMPT_VERSION}", file=sys.stderr)
    for index, case in enumerate(cases, 1):
        for model, client in clients.items():  # alternate models: each has its own limits
            result = await run_case(client, case)
            results[model].append(result)
            mark = "PASS" if result.passed else f"FAIL ({_why(result)})"
            print(f"[{index:2}/{len(cases)}] {model:<22} {case.id:<28} {mark}", file=sys.stderr)
            await asyncio.sleep(PACING_SECONDS / len(models))

    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "prompt_version": ASSISTANT_PROMPT_VERSION,
        "models": {m: {"summary": asdict(summarize(rs)), "results": [asdict(r) for r in rs]} for m, rs in results.items()},
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(f"\nPrompt {ASSISTANT_PROMPT_VERSION}  ({len(cases)} cases)")
    print(f"{'metric':<24}" + "".join(f"{m.split('/')[-1]:>16}" for m in models))
    for metric in METRICS:
        row = [getattr(summarize(results[m]), metric) for m in models]
        print(f"{metric:<24}" + "".join(f"{('-' if v is None else v)!s:>16}" for v in row))
    print("\nFailed cases:")
    for m in models:
        for r in results[m]:
            if not r.passed:
                seen = f"{r.called_tool}({r.called_args})" if r.called_tool else repr((r.answer or "")[:90])
                print(f"  {m.split('/')[-1]:<14} {r.case_id:<28} {_why(r):<16} → {seen}")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", default=[get_settings().ai_model])
    parser.add_argument("--only", nargs="*", help="run only these case ids")
    args = parser.parse_args()
    asyncio.run(main(args.models, args.only))
