import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.proposals import service
from app.ai.proposals.models import AIProposal, ProposalAction, ProposalStatus
from app.requests.models import RequestPriority, RequestStatus


class ProposalItemOut(BaseModel):
    """A request as it was when the proposal was made (the preview)."""

    request_id: uuid.UUID
    title: str
    status: RequestStatus
    priority: RequestPriority
    assignee_name: str | None


class ProposalOut(BaseModel):
    id: uuid.UUID
    action: ProposalAction
    status: ProposalStatus
    summary: str
    new_assignee_name: str | None
    new_priority: RequestPriority | None
    comment_body: str | None
    items: list[ProposalItemOut]
    # Send this back to approve: the approval binds to exactly what was shown.
    payload_hash: str
    expires_at: datetime
    created_at: datetime
    decided_at: datetime | None
    failure_code: str | None
    failure_detail: str | None


async def proposal_out(session: AsyncSession, proposal: AIProposal) -> ProposalOut:
    items = await service.proposal_items(session, proposal)
    assignee = await service.assignee_name(session, proposal)
    now = await session.scalar(select(func.now()))
    assert now is not None
    # A pending proposal past its expiry is shown as expired even before maintenance marks it.
    status = (
        ProposalStatus.EXPIRED
        if proposal.status == ProposalStatus.PENDING and proposal.expires_at <= now
        else proposal.status
    )
    return ProposalOut(
        id=proposal.id,
        action=proposal.action,
        status=status,
        summary=service.describe(proposal.action, len(items), assignee=assignee, priority=proposal.new_priority),
        new_assignee_name=assignee,
        new_priority=proposal.new_priority,
        comment_body=proposal.comment_body,
        items=[
            ProposalItemOut(
                request_id=i.request_id, title=i.title, status=i.status, priority=i.priority, assignee_name=i.assignee_name
            )
            for i in items
        ],
        payload_hash=proposal.payload_hash,
        expires_at=proposal.expires_at,
        created_at=proposal.created_at,
        decided_at=proposal.decided_at,
        failure_code=proposal.failure_code,
        failure_detail=proposal.failure_detail,
    )
