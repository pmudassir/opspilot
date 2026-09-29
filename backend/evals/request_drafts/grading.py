"""Deterministic grading for request-draft evals (no LLM judge)."""

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from app.ai.drafter import DraftFailure, ModelDraft

CASES_FILE = Path(__file__).with_name("cases.jsonl")
TITLE_MAX = 120  # the prompt asks for ≤ 120 characters

ORG_DEPARTMENTS = {
    "hotel": ["Front Desk", "Housekeeping", "IT", "Maintenance", "Security"],
    "helpdesk": ["Accounts & Access", "Hardware", "Network", "Software"],
}


@dataclass(frozen=True)
class Case:
    id: str
    org: str
    text: str
    departments: list[str | None]  # acceptable answers (None = "no department fits")
    priority: str  # the single best answer
    acceptable_priorities: list[str]
    tags: list[str]
    forbidden_in_title: list[str] = field(default_factory=list)

    @property
    def org_departments(self) -> list[str]:
        return ORG_DEPARTMENTS[self.org]


def load_cases(path: Path = CASES_FILE) -> list[Case]:
    return [Case(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    tags: list[str]
    failure: str | None  # DraftFailure value when no usable draft came back
    department: str | None = None
    priority: str | None = None
    title: str | None = None
    department_correct: bool = False
    priority_exact: bool = False
    priority_acceptable: bool = False
    title_ok: bool = False
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def passed(self) -> bool:
        return self.failure is None and self.department_correct and self.priority_acceptable and self.title_ok


def grade(case: Case, draft: ModelDraft | None, failure: DraftFailure | None, latency_ms: int) -> CaseResult:
    if draft is None:
        return CaseResult(case.id, case.tags, failure=(failure or DraftFailure.PROVIDER_ERROR).value, latency_ms=latency_ms)
    department = draft.department if draft.department in case.org_departments else None
    title = draft.title.strip()
    return CaseResult(
        case_id=case.id,
        tags=case.tags,
        failure=None,
        department=department,
        priority=draft.priority.value,
        title=title,
        department_correct=department in case.departments,
        priority_exact=draft.priority.value == case.priority,
        priority_acceptable=draft.priority.value in case.acceptable_priorities,
        title_ok=0 < len(title) <= TITLE_MAX
        and not any(word.lower() in title.lower() for word in case.forbidden_in_title),
        latency_ms=latency_ms,
        input_tokens=draft.usage.input_tokens,
        output_tokens=draft.usage.output_tokens,
    )


@dataclass(frozen=True)
class Summary:
    cases: int
    passed: int
    department_accuracy: float
    priority_exact: float
    priority_acceptable: float
    title_ok: float
    invalid_output_rate: float
    error_rate: float
    latency_p50_ms: float | None
    latency_p90_ms: float | None
    avg_input_tokens: float | None
    avg_output_tokens: float | None


def _rate(results: list[CaseResult], predicate) -> float:  # noqa: ANN001
    return round(sum(1 for r in results if predicate(r)) / len(results), 3) if results else 0.0


def summarize(results: list[CaseResult]) -> Summary:
    """Quality rates are over ALL cases: a failed call counts as wrong, not as skipped."""
    ok = [r for r in results if r.failure is None]
    latencies = sorted(r.latency_ms for r in ok)
    quantiles = statistics.quantiles(latencies, n=10) if len(latencies) >= 2 else None
    tokens_in = [r.input_tokens for r in ok if r.input_tokens is not None]
    tokens_out = [r.output_tokens for r in ok if r.output_tokens is not None]
    return Summary(
        cases=len(results),
        passed=sum(1 for r in results if r.passed),
        department_accuracy=_rate(results, lambda r: r.department_correct),
        priority_exact=_rate(results, lambda r: r.priority_exact),
        priority_acceptable=_rate(results, lambda r: r.priority_acceptable),
        title_ok=_rate(results, lambda r: r.title_ok),
        invalid_output_rate=_rate(results, lambda r: r.failure == DraftFailure.INVALID_OUTPUT.value),
        error_rate=_rate(results, lambda r: r.failure not in (None, DraftFailure.INVALID_OUTPUT.value)),
        latency_p50_ms=statistics.median(latencies) if latencies else None,
        latency_p90_ms=round(quantiles[8]) if quantiles else (latencies[0] if latencies else None),
        avg_input_tokens=round(statistics.mean(tokens_in)) if tokens_in else None,
        avg_output_tokens=round(statistics.mean(tokens_out)) if tokens_out else None,
    )
