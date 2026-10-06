"""Human-in-the-loop approvals for changes the assistant proposes.

The model can only *propose*. A proposal freezes an exact change: the action, its
parameters, the requests, and the version of each request the person saw. Nothing
happens until the proposer approves that exact preview; then normal lifecycle code
applies every item in ONE transaction, so all of it happens or none of it does.

  draft_proposal   read-only: resolve, check each request, snapshot (runs inside a tool)
  create_proposal  persist a draft as pending (with the assistant run's record)
  approve          lock → pending? same hash? not expired? → stage every item → executed,
                   or roll back to the savepoint → failed (lock kept, nothing changed)
  reject / expire_stale_proposals
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.proposals.models import (
    AIProposal,
    AIProposalItem,
    ProposalAction,
    ProposalStatus,
)
from app.comments.service import stage_comment
from app.errors import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
)
from app.organizations.models import Membership
from app.permissions import Permission, has_permission
from app.requests import lifecycle
from app.requests.lifecycle import (
    Change,
    InvalidTransitionError,
    RequestAction,
    StaleRequestError,
)
from app.requests.models import RequestPriority, RequestStatus
from app.requests.service import get_request, viewer_for
from app.users.models import User

MAX_ITEMS = 25
PROPOSAL_TTL = timedelta(minutes=10)
FAILURE_DETAIL_MAX = 500

_LIFECYCLE_ACTIONS = {
    ProposalAction.ASSIGN: RequestAction.ASSIGN,
    ProposalAction.UNASSIGN: RequestAction.UNASSIGN,
    ProposalAction.CANCEL: RequestAction.CANCEL,
    ProposalAction.CHANGE_PRIORITY: RequestAction.CHANGE_PRIORITY,
}


class ProposalClosedError(ConflictError):
    def __init__(self, status: ProposalStatus) -> None:
        super().__init__(f"This proposal is already {status}.")


class ProposalExpiredError(ConflictError):
    def __init__(self) -> None:
        super().__init__("This proposal expired. Ask again for a fresh one.")


class PayloadMismatchError(ConflictError):
    def __init__(self) -> None:
        super().__init__("This proposal doesn't match what was shown. Review it again.")


class NothingToProposeError(UnprocessableError):
    pass


@dataclass(frozen=True)
class ItemSnapshot:
    request_id: uuid.UUID
    updated_at: datetime  # the version the person sees
    title: str
    status: RequestStatus
    priority: RequestPriority
    assignee_name: str | None


@dataclass(frozen=True)
class Exclusion:
    request_id: uuid.UUID
    title: str
    reason: str


@dataclass(frozen=True)
class ProposalDraft:
    action: ProposalAction
    items: tuple[ItemSnapshot, ...]
    excluded: tuple[Exclusion, ...]
    new_assignee_membership_id: uuid.UUID | None = None
    new_assignee_name: str | None = None
    new_priority: RequestPriority | None = None
    comment_body: str | None = None


def _change(action: ProposalAction, assignee: uuid.UUID | None, priority: RequestPriority | None) -> Change | None:
    """The lifecycle change behind an action (comments aren't lifecycle actions)."""
    if action == ProposalAction.COMMENT:
        return None
    return Change(_LIFECYCLE_ACTIONS[action], assignee_membership_id=assignee, priority=priority)


async def _person_name(session: AsyncSession, organization_id: uuid.UUID, membership_id: uuid.UUID) -> str:
    name = await session.scalar(
        select(User.full_name)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == organization_id, Membership.id == membership_id)
    )
    if name is None:
        raise UnprocessableError("Assignee not found")
    return name


async def draft_proposal(
    session: AsyncSession,
    organization_id: uuid.UUID,
    membership: Membership,
    action: ProposalAction,
    request_ids: list[uuid.UUID],
    *,
    new_assignee_membership_id: uuid.UUID | None = None,
    new_priority: RequestPriority | None = None,
    comment_body: str | None = None,
) -> ProposalDraft:
    """Read-only. Checks each request as the proposer would act on it NOW: requests they
    can't change are excluded (with the reason), not silently dropped."""
    if not request_ids:
        raise NothingToProposeError("No requests to change.")
    if len(request_ids) > MAX_ITEMS:
        raise NothingToProposeError(f"At most {MAX_ITEMS} requests per proposal; narrow it down.")
    if action == ProposalAction.COMMENT and len(request_ids) != 1:
        raise NothingToProposeError("A comment goes on exactly one request.")
    change = _change(action, new_assignee_membership_id, new_priority)
    actor = await lifecycle.load_actor(session, membership)
    viewer = viewer_for(membership)

    items: list[ItemSnapshot] = []
    excluded: list[Exclusion] = []
    for request_id in dict.fromkeys(request_ids):  # de-duplicate, keep order
        row = await get_request(session, organization_id, request_id, viewer)  # 404 unless visible
        request = row.request
        try:
            if change is None:
                if not has_permission(membership.role, Permission.REQUESTS_COMMENT):
                    raise ForbiddenError("You can't comment on requests")
            else:
                await lifecycle.validate(session, request, actor, change)
        except DomainError as exc:
            excluded.append(Exclusion(request.id, request.title, exc.detail))
            continue
        items.append(
            ItemSnapshot(
                request.id, request.updated_at, request.title, request.status, request.priority, row.assignee_name
            )
        )
    if not items:
        reasons = "; ".join(f"{e.title}: {e.reason}" for e in excluded[:3])
        raise NothingToProposeError(f"None of these requests can be changed that way ({reasons}).")
    return ProposalDraft(
        action=action,
        items=tuple(items),
        excluded=tuple(excluded),
        new_assignee_membership_id=new_assignee_membership_id,
        new_assignee_name=(
            await _person_name(session, organization_id, new_assignee_membership_id)
            if new_assignee_membership_id
            else None
        ),
        new_priority=new_priority,
        comment_body=comment_body,
    )


def payload_hash(organization_id: uuid.UUID, proposer_membership_id: uuid.UUID, draft: ProposalDraft) -> str:
    """Binds an approval to exactly this change: any difference in action, parameters,
    requests or their versions gives a different hash."""
    canonical = {
        "v": 1,
        "organization_id": str(organization_id),
        "proposer": str(proposer_membership_id),
        "action": draft.action.value,
        "assignee": str(draft.new_assignee_membership_id) if draft.new_assignee_membership_id else None,
        "priority": draft.new_priority.value if draft.new_priority else None,
        "comment_body": draft.comment_body,
        "items": [[str(item.request_id), item.updated_at.isoformat()] for item in draft.items],
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def create_proposal(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    proposer_membership_id: uuid.UUID,
    run_id: uuid.UUID | None,
    draft: ProposalDraft,
    proposal_id: uuid.UUID | None = None,
) -> AIProposal:
    """Add a pending proposal to the caller's transaction (committed with the run record)."""
    proposal = AIProposal(
        id=proposal_id or uuid.uuid4(),
        organization_id=organization_id,
        proposer_membership_id=proposer_membership_id,
        run_id=run_id,
        action=draft.action,
        new_assignee_membership_id=draft.new_assignee_membership_id,
        new_priority=draft.new_priority,
        comment_body=draft.comment_body,
        payload_hash=payload_hash(organization_id, proposer_membership_id, draft),
        expires_at=func.now() + PROPOSAL_TTL,  # database clock
    )
    session.add(proposal)
    # Items reference the proposal by a composite FK the unit of work doesn't order by.
    await session.flush()
    session.add_all(
        AIProposalItem(
            proposal_id=proposal.id,
            request_id=item.request_id,
            organization_id=organization_id,
            position=position,
            expected_updated_at=item.updated_at,
            title=item.title,
            status=item.status,
            priority=item.priority,
            assignee_name=item.assignee_name,
        )
        for position, item in enumerate(draft.items)
    )
    return proposal


def describe(
    action: ProposalAction, count: int, *, assignee: str | None, priority: RequestPriority | None
) -> str:
    """The preview's headline, from data (not from the model): "Cancel 3 requests"."""
    requests = f"{count} request{'s' if count != 1 else ''}"
    match action:
        case ProposalAction.ASSIGN:
            return f"Assign {requests} to {assignee}"
        case ProposalAction.UNASSIGN:
            return f"Unassign {requests}"
        case ProposalAction.CANCEL:
            return f"Cancel {requests}"
        case ProposalAction.CHANGE_PRIORITY:
            assert priority is not None
            return f"Change the priority of {requests} to {priority.value}"
        case ProposalAction.COMMENT:
            return "Add a comment"
    raise AssertionError(action)


# --- reading -----------------------------------------------------------------


async def _load(
    session: AsyncSession, organization_id: uuid.UUID, membership_id: uuid.UUID, proposal_id: uuid.UUID, *, lock: bool
) -> AIProposal:
    """Only the proposer sees their proposal: anyone else gets 404, like another tenant."""
    query = select(AIProposal).where(
        AIProposal.organization_id == organization_id,
        AIProposal.id == proposal_id,
        AIProposal.proposer_membership_id == membership_id,
    )
    if lock:
        # Serializes approve/reject on this proposal: a double click waits here, then
        # sees the first one's outcome instead of executing again.
        query = query.with_for_update()
    proposal = await session.scalar(query.execution_options(populate_existing=True))
    if proposal is None:
        raise NotFoundError("Proposal")
    return proposal


async def get_proposal(
    session: AsyncSession, organization_id: uuid.UUID, membership_id: uuid.UUID, proposal_id: uuid.UUID
) -> AIProposal:
    return await _load(session, organization_id, membership_id, proposal_id, lock=False)


async def proposal_items(session: AsyncSession, proposal: AIProposal) -> list[AIProposalItem]:
    result = await session.scalars(
        select(AIProposalItem)
        .where(AIProposalItem.organization_id == proposal.organization_id, AIProposalItem.proposal_id == proposal.id)
        .order_by(AIProposalItem.position)
    )
    return list(result)


async def assignee_name(session: AsyncSession, proposal: AIProposal) -> str | None:
    if proposal.new_assignee_membership_id is None:
        return None
    return await _person_name(session, proposal.organization_id, proposal.new_assignee_membership_id)


# --- deciding ----------------------------------------------------------------


def _failure_code(exc: DomainError) -> str:
    match exc:
        case StaleRequestError() | lifecycle.ConcurrentChangeError():
            return "stale"
        case ForbiddenError():
            return "forbidden"
        case NotFoundError():
            return "not_found"
        case InvalidTransitionError():
            return "invalid_state"
        case UnprocessableError():
            return "invalid"
    return "conflict"


async def _apply_item(
    session: AsyncSession, proposal: AIProposal, item: AIProposalItem, membership: Membership
) -> None:
    event_data = {"approval_id": str(proposal.id)}
    change = _change(proposal.action, proposal.new_assignee_membership_id, proposal.new_priority)
    if change is not None:
        await lifecycle.stage(
            session, proposal.organization_id, item.request_id, membership, change,
            expected_updated_at=item.expected_updated_at, event_data=event_data,
        )
        return
    # A comment: same staleness rule as every other action (what you saw is what you approved).
    row = await get_request(session, proposal.organization_id, item.request_id, viewer_for(membership))
    if row.request.updated_at != item.expected_updated_at:
        raise StaleRequestError
    assert proposal.comment_body is not None
    await stage_comment(
        session, proposal.organization_id, item.request_id,
        author=membership, viewer=viewer_for(membership), body=proposal.comment_body,
    )


async def approve(
    session: AsyncSession,
    organization_id: uuid.UUID,
    membership: Membership,
    proposal_id: uuid.UUID,
    shown_payload_hash: str,
) -> AIProposal:
    """Approve and execute in one transaction. Idempotent: approving again (double click,
    retry) returns the recorded outcome without executing anything twice."""
    proposal = await _load(session, organization_id, membership.id, proposal_id, lock=True)
    if proposal.status in (ProposalStatus.EXECUTED, ProposalStatus.FAILED):
        return proposal
    if proposal.status != ProposalStatus.PENDING:
        raise ProposalClosedError(proposal.status)
    if shown_payload_hash != proposal.payload_hash:
        raise PayloadMismatchError
    now = await session.scalar(select(func.now()))
    assert now is not None
    if proposal.expires_at <= now:
        proposal.status = ProposalStatus.EXPIRED
        await session.commit()
        raise ProposalExpiredError

    failure: DomainError | None = None
    try:
        # Savepoint: on failure, undo every staged item but keep the proposal lock, so the
        # outcome is recorded in this same transaction (no window for a second attempt).
        async with session.begin_nested():
            for item in await proposal_items(session, proposal):
                await _apply_item(session, proposal, item, membership)
    except DomainError as exc:
        failure = exc
    proposal.status = ProposalStatus.FAILED if failure else ProposalStatus.EXECUTED
    proposal.decided_by_membership_id = membership.id
    proposal.decided_at = now
    if failure:
        proposal.failure_code = _failure_code(failure)
        proposal.failure_detail = failure.detail[:FAILURE_DETAIL_MAX]
    await session.commit()
    return proposal


async def reject(
    session: AsyncSession, organization_id: uuid.UUID, membership: Membership, proposal_id: uuid.UUID
) -> AIProposal:
    proposal = await _load(session, organization_id, membership.id, proposal_id, lock=True)
    if proposal.status == ProposalStatus.REJECTED:
        return proposal  # idempotent
    if proposal.status != ProposalStatus.PENDING:
        raise ProposalClosedError(proposal.status)
    proposal.status = ProposalStatus.REJECTED
    proposal.decided_by_membership_id = membership.id
    proposal.decided_at = await session.scalar(select(func.now()))
    await session.commit()
    return proposal


async def expire_stale_proposals(session: AsyncSession) -> int:
    """Mark pending proposals past their expiry as expired (maintenance; approve also checks)."""
    result = await session.execute(
        update(AIProposal)
        .where(AIProposal.status == ProposalStatus.PENDING, AIProposal.expires_at <= func.now())
        .values(status=ProposalStatus.EXPIRED)
        .returning(AIProposal.id)
    )
    count = len(result.all())
    await session.commit()
    return count
