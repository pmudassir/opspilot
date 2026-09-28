"""Request lifecycle transitions.

Each action: load the request as the actor sees it (404) → role may ever do this (403)
→ current state allows it (409) → object-level rule (403) → compare-and-set UPDATE
that only succeeds if the row still has the state we authorized against (else 409)
→ history event → commit, all in one transaction.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.departments.models import DepartmentMember
from app.errors import ConflictError, ForbiddenError, UnprocessableError
from app.organizations.models import Membership, MembershipRole, MembershipStatus
from app.permissions import Permission, has_permission
from app.requests.models import Request, RequestEventType, RequestStatus
from app.requests.service import RequestRow, get_request, record_event, viewer_for
from app.users.models import User


class RequestAction(StrEnum):
    ASSIGN = "assign"
    CLAIM = "claim"
    UNASSIGN = "unassign"
    START = "start"
    COMPLETE = "complete"
    CANCEL = "cancel"


@dataclass(frozen=True)
class Transition:
    from_statuses: frozenset[RequestStatus]
    to_status: RequestStatus
    event_type: RequestEventType


_ACTIVE = frozenset({RequestStatus.OPEN, RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS})

TRANSITIONS: dict[RequestAction, Transition] = {
    # Reassigning in-progress work returns it to ASSIGNED: the new assignee hasn't started.
    RequestAction.ASSIGN: Transition(_ACTIVE, RequestStatus.ASSIGNED, RequestEventType.ASSIGNED),
    RequestAction.CLAIM: Transition(
        frozenset({RequestStatus.OPEN}), RequestStatus.ASSIGNED, RequestEventType.ASSIGNED
    ),
    RequestAction.UNASSIGN: Transition(
        frozenset({RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS}),
        RequestStatus.OPEN,
        RequestEventType.UNASSIGNED,
    ),
    RequestAction.START: Transition(
        frozenset({RequestStatus.ASSIGNED}), RequestStatus.IN_PROGRESS, RequestEventType.STATUS_CHANGED
    ),
    RequestAction.COMPLETE: Transition(
        frozenset({RequestStatus.IN_PROGRESS}),
        RequestStatus.COMPLETED,
        RequestEventType.STATUS_CHANGED,
    ),
    RequestAction.CANCEL: Transition(_ACTIVE, RequestStatus.CANCELLED, RequestEventType.STATUS_CHANGED),
}

# Timestamp columns set when entering a status. COALESCE keeps the *first* assignment/start.
_ENTRY_TIMESTAMPS: dict[RequestStatus, dict[str, ColumnElement[Any]]] = {
    RequestStatus.ASSIGNED: {"assigned_at": func.coalesce(Request.assigned_at, func.now())},
    RequestStatus.IN_PROGRESS: {"started_at": func.coalesce(Request.started_at, func.now())},
    RequestStatus.COMPLETED: {"completed_at": func.now()},
    RequestStatus.CANCELLED: {"cancelled_at": func.now()},
}


class InvalidTransitionError(ConflictError):
    def __init__(self, action: RequestAction, status: RequestStatus) -> None:
        super().__init__(f"Cannot {action} a request that is {status}")


class ConcurrentChangeError(ConflictError):
    def __init__(self) -> None:
        super().__init__("The request was changed by someone else. Reload and try again.")


def _require(allowed: bool, message: str) -> None:
    if not allowed:
        raise ForbiddenError(message)


def _check_state(request: Request, action: RequestAction) -> None:
    if request.status not in TRANSITIONS[action].from_statuses:
        raise InvalidTransitionError(action, request.status)


async def _load(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, actor: Membership
) -> Request:
    return (await get_request(session, organization_id, request_id, viewer_for(actor))).request


async def _in_department(
    session: AsyncSession,
    organization_id: uuid.UUID,
    department_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> bool:
    found = await session.scalar(
        select(DepartmentMember.membership_id).where(
            DepartmentMember.organization_id == organization_id,
            DepartmentMember.department_id == department_id,
            DepartmentMember.membership_id == membership_id,
        )
    )
    return found is not None


async def _validate_assignee(
    session: AsyncSession, request: Request, assignee_membership_id: uuid.UUID
) -> str:
    """Assignee must be an active, non-member-role member of the request's department.
    Returns their name (snapshotted into the event)."""
    row = (
        await session.execute(
            select(Membership, User.full_name)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == request.organization_id,
                Membership.id == assignee_membership_id,
            )
        )
    ).first()
    if row is None:
        raise UnprocessableError("Assignee not found")
    membership, full_name = row
    if membership.status != MembershipStatus.ACTIVE:
        raise UnprocessableError("Assignee is deactivated")
    if membership.role == MembershipRole.MEMBER:
        raise UnprocessableError("Assignee must be staff (agent, manager or admin)")
    if not await _in_department(
        session, request.organization_id, request.department_id, assignee_membership_id
    ):
        raise UnprocessableError("Assignee must belong to the request's department")
    return full_name


async def _compare_and_set(
    session: AsyncSession, request: Request, values: dict[str, Any]
) -> bool:
    """UPDATE only if status and assignee are still what we authorized against.

    Two concurrent actions both pass their checks on the same snapshot; the database
    row lock makes the second UPDATE wait, re-check its WHERE against the committed
    row, and match 0 rows. That 0 is how we detect the lost update.
    """
    result = await session.execute(
        update(Request)
        .where(
            Request.organization_id == request.organization_id,
            Request.id == request.id,
            Request.status == request.status,
            Request.assignee_membership_id.is_not_distinct_from(request.assignee_membership_id),
        )
        .values(**values, updated_at=func.now())
        .returning(Request.id)
        .execution_options(synchronize_session=False)
    )
    return result.first() is not None


async def _apply(
    session: AsyncSession,
    request: Request,
    actor: Membership,
    action: RequestAction,
    *,
    assignee_membership_id: uuid.UUID | None,
    data: dict[str, Any] | None = None,
) -> RequestRow:
    transition = TRANSITIONS[action]
    values: dict[str, Any] = {
        "status": transition.to_status,
        "assignee_membership_id": assignee_membership_id,
        **_ENTRY_TIMESTAMPS.get(transition.to_status, {}),
    }
    if not await _compare_and_set(session, request, values):
        await session.rollback()
        raise ConcurrentChangeError
    record_event(
        session,
        request,
        actor_membership_id=actor.id,
        event_type=transition.event_type,
        from_status=request.status,
        to_status=transition.to_status,
        data=data,
    )
    await session.commit()
    return await get_request(session, request.organization_id, request.id, viewer_for(actor))


async def assign(
    session: AsyncSession,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    actor: Membership,
    assignee_membership_id: uuid.UUID,
) -> RequestRow:
    request = await _load(session, organization_id, request_id, actor)
    _require(
        has_permission(actor.role, Permission.REQUESTS_ASSIGN),
        "Only managers and admins can assign requests",
    )
    _check_state(request, RequestAction.ASSIGN)
    if request.assignee_membership_id == assignee_membership_id:
        # Idempotent: already assigned to this person (a retry, or a double click).
        return await get_request(session, organization_id, request_id, viewer_for(actor))
    assignee_name = await _validate_assignee(session, request, assignee_membership_id)
    return await _apply(
        session,
        request,
        actor,
        RequestAction.ASSIGN,
        assignee_membership_id=assignee_membership_id,
        data={
            "assignee_membership_id": str(assignee_membership_id),
            "assignee_name": assignee_name,
            "previous_assignee_membership_id": (
                str(request.assignee_membership_id) if request.assignee_membership_id else None
            ),
        },
    )


async def claim(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, actor: Membership
) -> RequestRow:
    request = await _load(session, organization_id, request_id, actor)
    _require(has_permission(actor.role, Permission.REQUESTS_CLAIM), "Only staff can claim requests")
    _check_state(request, RequestAction.CLAIM)
    _require(
        await _in_department(session, organization_id, request.department_id, actor.id),
        "You can only claim requests in your own departments",
    )
    return await _apply(
        session,
        request,
        actor,
        RequestAction.CLAIM,
        assignee_membership_id=actor.id,
        data={"assignee_membership_id": str(actor.id), "claimed": True},
    )


async def unassign(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, actor: Membership
) -> RequestRow:
    request = await _load(session, organization_id, request_id, actor)
    _require(
        has_permission(actor.role, Permission.REQUESTS_ASSIGN),
        "Only managers and admins can unassign requests",
    )
    _check_state(request, RequestAction.UNASSIGN)
    return await _apply(
        session,
        request,
        actor,
        RequestAction.UNASSIGN,
        assignee_membership_id=None,
        data={"previous_assignee_membership_id": str(request.assignee_membership_id)},
    )


async def _work(
    session: AsyncSession,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    actor: Membership,
    action: RequestAction,
) -> RequestRow:
    request = await _load(session, organization_id, request_id, actor)
    _require(has_permission(actor.role, Permission.REQUESTS_WORK), f"Only staff can {action} requests")
    _check_state(request, action)
    _require(
        has_permission(actor.role, Permission.REQUESTS_WORK_ANY)
        or request.assignee_membership_id == actor.id,
        f"Only the assignee can {action} this request",
    )
    return await _apply(
        session, request, actor, action, assignee_membership_id=request.assignee_membership_id
    )


async def start(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, actor: Membership
) -> RequestRow:
    return await _work(session, organization_id, request_id, actor, RequestAction.START)


async def complete(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, actor: Membership
) -> RequestRow:
    return await _work(session, organization_id, request_id, actor, RequestAction.COMPLETE)


async def cancel(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, actor: Membership
) -> RequestRow:
    request = await _load(session, organization_id, request_id, actor)
    _check_state(request, RequestAction.CANCEL)
    is_own_open_request = (
        request.requester_membership_id == actor.id and request.status == RequestStatus.OPEN
    )
    _require(
        has_permission(actor.role, Permission.REQUESTS_CANCEL_ANY) or is_own_open_request,
        "Requesters can only cancel their own requests while they are still open",
    )
    return await _apply(
        session,
        request,
        actor,
        RequestAction.CANCEL,
        assignee_membership_id=request.assignee_membership_id,
    )
