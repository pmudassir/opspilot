"""Draft a request from free text. The result is a suggestion for a human to review;
nothing is saved except a usage record (no prompt or output text)."""

import math
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.drafter import DrafterError, DraftFailure, RequestDrafter, TokenUsage
from app.ai.models import AIUsage, AIUsageOutcome
from app.ai.prompts import PROMPT_VERSION
from app.departments.service import list_departments
from app.errors import DomainError
from app.requests.models import RequestPriority

FEATURE = "request_draft"
QUOTA_WINDOW = timedelta(hours=1)


class AIUnavailableError(DomainError):
    status_code = 503

    def __init__(self) -> None:
        super().__init__("AI drafting isn't available. Please fill in the request yourself.")


class AIQuotaExceededError(DomainError):
    status_code = 429

    def __init__(self, retry_after_seconds: int) -> None:
        minutes = max(1, math.ceil(retry_after_seconds / 60))
        super().__init__(f"You've used your AI drafts for now. Try again in {minutes} min, or fill it in yourself.")
        self.headers = {"Retry-After": str(retry_after_seconds)}


class AIDraftFailedError(DomainError):
    _MESSAGES = {
        DraftFailure.TIMEOUT: (504, "The AI took too long to respond."),
        DraftFailure.RATE_LIMITED: (503, "The AI service is busy right now."),
        DraftFailure.PROVIDER_ERROR: (502, "The AI service had a problem."),
        DraftFailure.INVALID_OUTPUT: (502, "The AI produced an unusable draft."),
    }

    def __init__(self, failure: DraftFailure, retry_after_seconds: int | None) -> None:
        status_code, message = self._MESSAGES[failure]
        super().__init__(f"{message} Please try again or fill in the request yourself.")
        self.status_code = status_code
        if retry_after_seconds:
            self.headers = {"Retry-After": str(retry_after_seconds)}


@dataclass(frozen=True)
class RequestDraftResult:
    title: str
    description: str
    department_id: uuid.UUID | None
    department_name: str | None
    priority: RequestPriority
    rationale: str
    model: str


async def quota_retry_after(
    session: AsyncSession, organization_id: uuid.UUID, membership_id: uuid.UUID, *, feature: str, per_hour: int
) -> int | None:
    """Seconds until this member may use `feature` again, or None if under quota.
    Every attempt counts (failures cost provider quota too)."""
    count, oldest = (
        await session.execute(
            select(func.count(), func.min(AIUsage.created_at)).where(
                AIUsage.organization_id == organization_id,
                AIUsage.membership_id == membership_id,
                AIUsage.feature == feature,
                AIUsage.created_at > func.now() - QUOTA_WINDOW,
            )
        )
    ).one()
    if count < per_hour:
        return None
    now = await session.scalar(select(func.now()))
    assert now is not None and oldest is not None
    return max(1, math.ceil((oldest + QUOTA_WINDOW - now).total_seconds()))


async def _record(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    drafter: RequestDrafter,
    outcome: AIUsageOutcome,
    started: float,
    usage: TokenUsage | None,
) -> None:
    session.add(
        AIUsage(
            organization_id=organization_id,
            membership_id=membership_id,
            feature=FEATURE,
            provider=drafter.provider,
            model=drafter.model,
            prompt_version=PROMPT_VERSION,
            outcome=outcome,
            latency_ms=round((time.perf_counter() - started) * 1000),
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
        )
    )
    await session.commit()


async def draft_request(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    text: str,
    drafter: RequestDrafter | None,
    quota_per_hour: int,
) -> RequestDraftResult:
    if drafter is None:
        raise AIUnavailableError
    retry_after = await quota_retry_after(
        session, organization_id, membership_id, feature=FEATURE, per_hour=quota_per_hour
    )
    if retry_after is not None:
        raise AIQuotaExceededError(retry_after)
    departments = await list_departments(session, organization_id)
    # End the read transaction: the provider call can take seconds, and an open
    # transaction would pin a pooled connection ("idle in transaction") meanwhile.
    await session.commit()

    started = time.perf_counter()
    record = dict(organization_id=organization_id, membership_id=membership_id, drafter=drafter, started=started)
    try:
        suggestion = await drafter.draft(text=text, departments=[d.name for d in departments])
    except DrafterError as exc:
        await _record(session, **record, outcome=AIUsageOutcome(exc.failure.value), usage=None)
        raise AIDraftFailedError(exc.failure, exc.retry_after_seconds) from exc
    await _record(session, **record, outcome=AIUsageOutcome.SUCCESS, usage=suggestion.usage)

    # The model names a department; only a name that exists in THIS org maps to an id.
    # Anything else (hallucinated, another tenant's, empty) becomes "no suggestion".
    by_name = {d.name.casefold(): d for d in departments}
    department = by_name.get(suggestion.department.casefold()) if suggestion.department else None
    return RequestDraftResult(
        title=suggestion.title,
        description=suggestion.description,
        department_id=department.id if department else None,
        department_name=department.name if department else None,
        priority=suggestion.priority,
        rationale=suggestion.rationale,
        model=drafter.model,
    )
