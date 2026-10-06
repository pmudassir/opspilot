import uuid

from fastapi import APIRouter
from pydantic import Field

from app.ai.proposals import service
from app.ai.proposals.schemas import ProposalOut, proposal_out
from app.db import SessionDep
from app.permissions import Permission
from app.schemas import StrictRequest
from app.tenancy import authorized

router = APIRouter(prefix="/api/v1/orgs/{org_id}/ai/proposals", tags=["ai"])


class ApproveBody(StrictRequest):
    payload_hash: str = Field(min_length=64, max_length=64)


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
