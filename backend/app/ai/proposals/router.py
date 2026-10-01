import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.proposals import service
from app.ai.proposals.models import AIProposal, ProposalAction, ProposalStatus
from app.db import SessionDep
from app.permissions import Permission
from app.requests.models import RequestPriority, RequestStatus
from app.schemas import StrictRequest
from app.tenancy import authorized

router = APIRouter(prefix="/api/v1/orgs/{org_id}/ai/proposals", tags=["ai"])


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


class ApproveBody(StrictRequest):
    payload_hash: str = Field(min_length=64, max_length=64)


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


@router.get("/{proposal_id}")
async def get_proposal(
    proposal_id: uuid.UUID,
    context: authorized(Permission.REQUESTS_READ),  # type: ignore[valid-type]
    session: SessionDep,
) -> ProposalOut:
    proposal = await service.get_proposal(session, context.organization_id, context.membership.id, proposal_id)
    return await proposal_out(session, proposal)


@router.post("/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: uuid.UUID,
    body: ApproveBody,
    context: authorized(Permission.REQUESTS_READ),  # type: ignore[valid-type]
    session: SessionDep,
) -> ProposalOut:
    """Executes the exact previewed change, all or nothing. Approving again returns the
    recorded outcome (executed or failed) without executing twice."""
    membership_id = context.membership.id
    proposal = await service.approve(session, context.organization_id, context.membership, proposal_id, body.payload_hash)
    proposal = await service.get_proposal(session, context.organization_id, membership_id, proposal.id)
    return await proposal_out(session, proposal)


@router.post("/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: uuid.UUID,
    context: authorized(Permission.REQUESTS_READ),  # type: ignore[valid-type]
    session: SessionDep,
) -> ProposalOut:
    membership_id = context.membership.id
    proposal = await service.reject(session, context.organization_id, context.membership, proposal_id)
    proposal = await service.get_proposal(session, context.organization_id, membership_id, proposal.id)
    return await proposal_out(session, proposal)
