"""Ask OpsPilot: one question in, one answer out. Nothing is changed and no text is stored.

Order: model configured? → request in context visible? → quota → release the DB
connection → loop (model ↔ executor) → record the run + its tool calls (metadata only)
→ references for the refs the answer mentions.
"""

import math
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assistant.executor import ToolCallRecord, ToolExecutor
from app.ai.assistant.model import SystemMessage, ToolCallingModel, UserMessage
from app.ai.assistant.prompts import ASSISTANT_PROMPT_VERSION, system_prompt
from app.ai.assistant.refs import RefRegistry
from app.ai.assistant.runner import RunFailedError, run
from app.ai.assistant.tools import tool_definition, tools_for
from app.ai.drafter import DraftFailure, TokenUsage
from app.ai.models import AIToolCall, AIUsage, AIUsageOutcome
from app.ai.service import quota_retry_after
from app.departments.models import Department, DepartmentMember
from app.errors import DomainError
from app.organizations.models import MembershipRole
from app.requests.service import Viewer, request_titles, viewer_for
from app.tenancy import TenantContext

FEATURE = "assistant"
_REF_PATTERN = re.compile(r"\bR([0-9]{1,3})\b")


class AssistantUnavailableError(DomainError):
    status_code = 503

    def __init__(self) -> None:
        super().__init__("The assistant isn't available.")


class AssistantQuotaExceededError(DomainError):
    status_code = 429

    def __init__(self, retry_after_seconds: int) -> None:
        minutes = max(1, math.ceil(retry_after_seconds / 60))
        super().__init__(f"You've asked a lot of questions this hour. Try again in {minutes} min.")
        self.headers = {"Retry-After": str(retry_after_seconds)}


class AssistantFailedError(DomainError):
    _MESSAGES = {
        DraftFailure.TIMEOUT: (504, "The assistant took too long to answer."),
        DraftFailure.RATE_LIMITED: (503, "The AI service is busy right now."),
        DraftFailure.PROVIDER_ERROR: (502, "The AI service had a problem."),
        DraftFailure.INVALID_OUTPUT: (502, "The assistant produced an unusable answer."),
    }

    def __init__(self, failure: DraftFailure, retry_after_seconds: int | None) -> None:
        status_code, message = self._MESSAGES[failure]
        super().__init__(f"{message} Please try again.")
        self.status_code = status_code
        if retry_after_seconds:
            self.headers = {"Retry-After": str(retry_after_seconds)}


@dataclass(frozen=True)
class _Caller:
    """Plain values captured once at the start. The ORM objects in TenantContext get
    expired by any rollback during the run (e.g. a failed tool call), and touching an
    expired attribute would mean lazy I/O, which async sessions don't allow."""

    organization_id: uuid.UUID
    membership_id: uuid.UUID
    role: MembershipRole
    full_name: str
    viewer: Viewer

    @classmethod
    def of(cls, context: TenantContext) -> "_Caller":
        return cls(
            organization_id=context.organization_id,
            membership_id=context.membership.id,
            role=context.membership.role,
            full_name=context.user.full_name,
            viewer=viewer_for(context.membership),
        )


@dataclass(frozen=True)
class Reference:
    ref: str
    request_id: uuid.UUID
    title: str


@dataclass(frozen=True)
class AssistantAnswer:
    answer: str
    references: list[Reference]
    tools_used: list[ToolCallRecord]
    model: str
    as_of: datetime


async def _department_names(session: AsyncSession, caller: _Caller) -> list[str]:
    result = await session.scalars(
        select(Department.name)
        .join(
            DepartmentMember,
            (DepartmentMember.organization_id == Department.organization_id)
            & (DepartmentMember.department_id == Department.id),
        )
        .where(
            DepartmentMember.organization_id == caller.organization_id,
            DepartmentMember.membership_id == caller.membership_id,
        )
        .order_by(Department.name)
    )
    return list(result)


async def _record(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    caller: _Caller,
    model: ToolCallingModel,
    outcome: AIUsageOutcome,
    started: float,
    usage: TokenUsage,
    tool_calls: tuple[ToolCallRecord, ...],
) -> None:
    """The run and its tool calls, together (one transaction). No question, answer,
    arguments or results: only what's needed for cost, latency, quota and debugging."""
    if session.in_transaction():
        await session.rollback()  # e.g. a tool call cut off by the run deadline
    session.add(
        AIUsage(
            id=run_id,
            organization_id=caller.organization_id,
            membership_id=caller.membership_id,
            feature=FEATURE,
            provider=model.provider,
            model=model.model,
            prompt_version=ASSISTANT_PROMPT_VERSION,
            outcome=outcome,
            latency_ms=round((time.perf_counter() - started) * 1000),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
    )
    # The unit of work doesn't order these by the composite FK (no relationship()): run row first.
    await session.flush()
    session.add_all(
        AIToolCall(
            organization_id=caller.organization_id,
            run_id=run_id,
            step=step,
            tool=record.tool,
            status=record.status,
            latency_ms=record.latency_ms,
            result_count=record.result_count,
        )
        for step, record in enumerate(tool_calls, start=1)
    )
    await session.commit()


async def _references(
    session: AsyncSession, caller: _Caller, refs: RefRegistry, answer: str
) -> list[Reference]:
    """Links for the refs the answer mentions: only refs this run registered, and only
    requests still visible to the user. The model never supplies a link or an id."""
    mentioned = dict.fromkeys(f"R{number}" for number in _REF_PATTERN.findall(answer))
    ids = {ref: request_id for ref in mentioned if (request_id := refs.resolve(ref)) is not None}
    titles = await request_titles(session, caller.organization_id, caller.viewer, list(ids.values()))
    return [Reference(ref, request_id, titles[request_id]) for ref, request_id in ids.items() if request_id in titles]


async def ask(
    session: AsyncSession,
    context: TenantContext,
    *,
    question: str,
    request_id: uuid.UUID | None,
    model: ToolCallingModel | None,
    quota_per_hour: int,
) -> AssistantAnswer:
    if model is None:
        raise AssistantUnavailableError

    caller = _Caller.of(context)
    run_id = uuid.uuid4()
    refs = RefRegistry()
    departments = await _department_names(session, caller)
    now = await session.scalar(select(func.now()))
    assert now is not None
    await session.commit()  # the executor needs an idle session

    executor = ToolExecutor(
        session,
        organization_id=caller.organization_id,
        membership_id=caller.membership_id,
        refs=refs,
        run_id=run_id,
    )
    user_message = question
    if request_id is not None:
        ref = await executor.register_request(request_id)  # 404 unless visible
        user_message = f"(The user is looking at request {ref}.)\n\n{question}"

    retry_after = await quota_retry_after(
        session, caller.organization_id, caller.membership_id, feature=FEATURE, per_hour=quota_per_hour
    )
    if retry_after is not None:
        raise AssistantQuotaExceededError(retry_after)
    # Don't hold a pooled connection while waiting on the model.
    await session.commit()

    prompt = system_prompt(
        name=caller.full_name,
        role=caller.role.value,
        departments=departments,
        now=now.strftime("%Y-%m-%d %H:%M"),
    )
    tools = [tool_definition(tool) for tool in tools_for(caller.role)]
    record = dict(run_id=run_id, caller=caller, model=model, started=time.perf_counter())
    try:
        result = await run(
            model, executor, messages=[SystemMessage(prompt), UserMessage(user_message)], tools=tools
        )
    except RunFailedError as exc:
        await _record(session, **record, outcome=AIUsageOutcome(exc.failure.value), usage=exc.usage, tool_calls=exc.tool_calls)
        raise AssistantFailedError(exc.failure, exc.retry_after_seconds) from exc
    await _record(session, **record, outcome=AIUsageOutcome.SUCCESS, usage=result.usage, tool_calls=result.tool_calls)

    references = await _references(session, caller, refs, result.answer)
    as_of = await session.scalar(select(func.now()))
    assert as_of is not None
    return AssistantAnswer(result.answer, references, list(result.tool_calls), model.model, as_of)
