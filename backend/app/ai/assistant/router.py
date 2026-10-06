import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.ai.assistant import service
from app.ai.dependencies import AssistantModelDep
from app.ai.models import ToolCallStatus
from app.ai.proposals.schemas import ProposalOut, proposal_out
from app.ai.proposals.service import get_proposal
from app.config import SettingsDep
from app.db import SessionDep
from app.errors import UnprocessableError
from app.permissions import Permission
from app.schemas import StrictRequest, trimmed_str
from app.tenancy import authorized

router = APIRouter(prefix="/api/v1/orgs/{org_id}/ai", tags=["ai"])

QUESTION_MIN = 3
QUESTION_MAX = 500  # bounds cost per run


class AskBody(StrictRequest):
    question: trimmed_str(QUESTION_MAX)  # type: ignore[valid-type]
    # The request the user is looking at, if any. It must be visible to them (404 otherwise).
    request_id: uuid.UUID | None = None


class ReferenceOut(BaseModel):
    ref: str
    request_id: uuid.UUID
    title: str


class ToolUseOut(BaseModel):
    tool: str
    status: ToolCallStatus


class AssistantAnswerOut(BaseModel):
    """Nothing was changed. `references` link the refs (R1, ...) in `answer`; a `proposal`
    only takes effect if the user approves it (POST /ai/proposals/{id}/approve)."""

    answer: str
    references: list[ReferenceOut]
    tools_used: list[ToolUseOut]
    model: str
    as_of: datetime
    # A change the assistant proposed: nothing happens until the user approves it.
    proposal: ProposalOut | None


@router.post("/assistant")
async def ask(
    body: AskBody,
    context: authorized(Permission.REQUESTS_READ),  # type: ignore[valid-type]
    session: SessionDep,
    settings: SettingsDep,
    model: AssistantModelDep,
) -> AssistantAnswerOut:
    if len(body.question) < QUESTION_MIN:
        raise UnprocessableError(f"Ask a question of at least {QUESTION_MIN} characters.")
    membership_id = context.membership.id
    result = await service.ask(
        session,
        context,
        question=body.question,
        request_id=body.request_id,
        model=model,
        quota_per_hour=settings.ai_assistant_runs_per_hour,
    )
    return AssistantAnswerOut(
        answer=result.answer,
        references=[ReferenceOut(**r.__dict__) for r in result.references],
        tools_used=[ToolUseOut(tool=t.tool, status=t.status) for t in result.tools_used],
        model=result.model,
        as_of=result.as_of,
        proposal=(
            await proposal_out(
                session, await get_proposal(session, context.organization_id, membership_id, result.proposal_id)
            )
            if result.proposal_id
            else None
        ),
    )
