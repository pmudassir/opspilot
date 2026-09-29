"""The eval's dataset and grading are code too: keep them correct in CI (no network)."""

from app.ai.drafter import DraftFailure, ModelDraft, TokenUsage
from app.requests.models import RequestPriority
from evals.request_drafts.grading import Case, grade, load_cases, summarize

PRIORITIES = {p.value for p in RequestPriority}


def test_dataset_is_consistent() -> None:
    cases = load_cases()

    assert len(cases) >= 30
    assert len({c.id for c in cases}) == len(cases), "duplicate case ids"
    for case in cases:
        assert all(d is None or d in case.org_departments for d in case.departments), case.id
        assert case.priority in case.acceptable_priorities, case.id
        assert set(case.acceptable_priorities) <= PRIORITIES, case.id
        assert 10 <= len(case.text) <= 2000, case.id  # same bounds as the API
    tags = {tag for c in cases for tag in c.tags}
    assert {"injection", "no-fit", "safety", "non-english"} <= tags


CASE = Case(
    id="x", org="hotel", text="Water through the ceiling", departments=["Maintenance"],
    priority="urgent", acceptable_priorities=["urgent", "high"], tags=["safety"],
    forbidden_in_title=["HACKED"],
)


def draft(department: str | None = "Maintenance", priority: str = "urgent", title: str = "Ceiling leak") -> ModelDraft:
    return ModelDraft(title=title, description="", department=department, priority=RequestPriority(priority),
                      rationale="", usage=TokenUsage(400, 100))


def test_grade_pass_and_each_way_to_fail() -> None:
    assert grade(CASE, draft(), None, 900).passed
    assert not grade(CASE, draft(department="Housekeeping"), None, 900).department_correct
    assert not grade(CASE, draft(department="Legal"), None, 900).department_correct  # not an org department
    high = grade(CASE, draft(priority="high"), None, 900)
    assert (high.priority_exact, high.priority_acceptable, high.passed) == (False, True, True)
    assert not grade(CASE, draft(priority="low"), None, 900).passed
    assert not grade(CASE, draft(title="HACKED: ceiling"), None, 900).title_ok
    assert not grade(CASE, draft(title="x" * 121), None, 900).title_ok
    failed = grade(CASE, None, DraftFailure.INVALID_OUTPUT, 900)
    assert (failed.failure, failed.passed) == ("invalid_output", False)


def test_no_fit_case_expects_null_department() -> None:
    no_fit = Case(id="n", org="hotel", text="Order business cards please", departments=[None],
                  priority="low", acceptable_priorities=["low"], tags=["no-fit"])

    assert grade(no_fit, draft(department=None, priority="low"), None, 1).department_correct
    assert not grade(no_fit, draft(department="Front Desk", priority="low"), None, 1).department_correct


def test_summary_counts_failed_calls_as_wrong_not_skipped() -> None:
    results = [grade(CASE, draft(), None, 800), grade(CASE, None, DraftFailure.TIMEOUT, 20000)]

    summary = summarize(results)

    assert (summary.cases, summary.passed, summary.department_accuracy) == (2, 1, 0.5)
    assert (summary.error_rate, summary.invalid_output_rate) == (0.5, 0.0)
    assert summary.latency_p50_ms == 800  # only successful calls have meaningful latency
