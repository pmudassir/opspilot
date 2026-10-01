"""Request lifecycle transitions.

Each action: load the request as the actor sees it (404) → role may ever do this (403)
→ current state allows it (409) → object-level rule (403) → compare-and-set UPDATE
that only succeeds if the row still has the state we authorized against (else 409)
→ history event → commit, all in one transaction.

The checks are pure functions returning the reason an action is *not* allowed.
Enforcement raises that reason; `allowed_actions()` lists actions without one, so the
UI's buttons and the API's enforcement can never disagree.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.departments.models import DepartmentMember
from app.errors import ConflictError, DomainError, ForbiddenError, UnprocessableError
from app.organizations.models import Membership, MembershipRole, MembershipStatus
from app.permissions import Permission, has_permission
from app.requests.models import (
    Request,
    RequestEventType,
    RequestPriority,
    RequestStatus,
)
from app.requests.service import RequestRow, get_request, record_event, viewer_for
from app.users.models import User


class RequestAction(StrEnum):
    ASSIGN = "assign"
    CLAIM = "claim"
    UNASSIGN = "unassign"
    START = "start"
    COMPLETE = "complete"
    CANCEL = "cancel"
    # Not a status transition, but advertised and authorized the same way.
    CHANGE_PRIORITY = "change_priority"


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
        super().__init__(f"Cannot {action.replace('_', ' ')} a request that is {status}")


class ConcurrentChangeError(ConflictError):
    def __init__(self) -> None:
        super().__init__("The request was changed by someone else. Reload and try again.")


class StaleRequestError(ConflictError):
    """The request changed after someone reviewed it (e.g. an approval preview)."""

    def __init__(self) -> None:
        super().__init__("The request changed since it was reviewed. Review it again.")


@dataclass(frozen=True)
class Change:
    """One action and the parameters it needs."""

    action: RequestAction
    assignee_membership_id: uuid.UUID | None = None  # ASSIGN
    priority: RequestPriority | None = None  # CHANGE_PRIORITY


@dataclass(frozen=True)
class Actor:
    """The acting membership plus what object-level rules need (its departments)."""

    membership_id: uuid.UUID
    role: MembershipRole
    department_ids: frozenset[uuid.UUID]

    def can(self, permission: Permission) -> bool:
        return has_permission(self.role, permission)


async def load_actor(session: AsyncSession, membership: Membership) -> Actor:
    """One query per HTTP request (not per listed row)."""
    department_ids = await session.scalars(
        select(DepartmentMember.department_id).where(
            DepartmentMember.organization_id == membership.organization_id,
            DepartmentMember.membership_id == membership.id,
        )
    )
    return Actor(membership.id, membership.role, frozenset(department_ids))


# --- rules: each returns why the action is NOT allowed, or None ------------------


def _state_violation(request: Request, action: RequestAction) -> DomainError | None:
    if request.status not in TRANSITIONS[action].from_statuses:
        return InvalidTransitionError(action, request.status)
    return None


def _assign_violation(request: Request, actor: Actor, action: RequestAction) -> DomainError | None:
    if not actor.can(Permission.REQUESTS_ASSIGN):
        return ForbiddenError(f"Only managers and admins can {action} requests")
    return _state_violation(request, action)


def _claim_violation(request: Request, actor: Actor, action: RequestAction) -> DomainError | None:
    if not actor.can(Permission.REQUESTS_CLAIM):
        return ForbiddenError("Only staff can claim requests")
    if violation := _state_violation(request, action):
        return violation
    if request.department_id not in actor.department_ids:
        return ForbiddenError("You can only claim requests in your own departments")
    return None


def _work_violation(request: Request, actor: Actor, action: RequestAction) -> DomainError | None:
    if not actor.can(Permission.REQUESTS_WORK):
        return ForbiddenError(f"Only staff can {action} requests")
    if violation := _state_violation(request, action):
        return violation
    if not (
        actor.can(Permission.REQUESTS_WORK_ANY)
        or request.assignee_membership_id == actor.membership_id
    ):
        return ForbiddenError(f"Only the assignee can {action} this request")
    return None


def _cancel_violation(request: Request, actor: Actor, action: RequestAction) -> DomainError | None:
    if violation := _state_violation(request, action):
        return violation
    is_own_open_request = (
        request.requester_membership_id == actor.membership_id
        and request.status == RequestStatus.OPEN
    )
    if not (actor.can(Permission.REQUESTS_CANCEL_ANY) or is_own_open_request):
        return ForbiddenError(
            "Requesters can only cancel their own requests while they are still open"
        )
    return None


def _priority_violation(request: Request, actor: Actor, action: RequestAction) -> DomainError | None:
    if request.status not in _ACTIVE:
        return InvalidTransitionError(action, request.status)
    if not actor.can(Permission.REQUESTS_PRIORITIZE):
        return ForbiddenError("Only managers and admins can change a request's priority")
    return None


_RULES: dict[RequestAction, Callable[[Request, Actor, RequestAction], DomainError | None]] = {
    RequestAction.ASSIGN: _assign_violation,
    RequestAction.CLAIM: _claim_violation,
    RequestAction.UNASSIGN: _assign_violation,
    RequestAction.START: _work_violation,
    RequestAction.COMPLETE: _work_violation,
    RequestAction.CANCEL: _cancel_violation,
    RequestAction.CHANGE_PRIORITY: _priority_violation,
}


def check(action: RequestAction, request: Request, actor: Actor) -> None:
    """Raise the reason this actor may not perform this action now (403/409)."""
    if violation := _RULES[action](request, actor, action):
        raise violation


def allowed_actions(request: Request, actor: Actor) -> list[RequestAction]:
    """What the actor may do to this request right now (drives the UI's buttons)."""
    return [action for action in RequestAction if _RULES[action](request, actor, action) is None]


# --- execution ------------------------------------------------------------------


async def _load(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, membership: Membership
) -> Request:
    return (await get_request(session, organization_id, request_id, viewer_for(membership))).request


async def _authorize(
    session: AsyncSession,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    membership: Membership,
    action: RequestAction,
) -> Request:
    request = await _load(session, organization_id, request_id, membership)  # 404
    check(action, request, await load_actor(session, membership))  # 403 / 409
    return request


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
    in_department = await session.scalar(
        select(DepartmentMember.membership_id).where(
            DepartmentMember.organization_id == request.organization_id,
            DepartmentMember.department_id == request.department_id,
            DepartmentMember.membership_id == assignee_membership_id,
        )
    )
    if in_department is None:
        raise UnprocessableError("Assignee must belong to the request's department")
    return full_name


async def _compare_and_set(
    session: AsyncSession,
    request: Request,
    values: dict[str, Any],
    *,
    guard_priority: bool = False,
    expected_updated_at: datetime | None = None,
) -> bool:
    """UPDATE only if status and assignee are still what we authorized against.

    Two concurrent actions both pass their checks on the same snapshot; the database
    row lock makes the second UPDATE wait, re-check its WHERE against the committed
    row, and match 0 rows. That 0 is how we detect the lost update.
    `expected_updated_at` makes it "nothing at all changed since it was reviewed".
    """
    guards = [
        Request.organization_id == request.organization_id,
        Request.id == request.id,
        Request.status == request.status,
        Request.assignee_membership_id.is_not_distinct_from(request.assignee_membership_id),
    ]
    if guard_priority:
        guards.append(Request.priority == request.priority)
    if expected_updated_at is not None:
        guards.append(Request.updated_at == expected_updated_at)
    result = await session.execute(
        update(Request)
        .where(*guards)
        .values(**values, updated_at=func.now())
        .returning(Request.id)
        .execution_options(synchronize_session=False)
    )
    return result.first() is not None


async def _apply(
    session: AsyncSession,
    request: Request,
    membership: Membership,
    action: RequestAction,
    *,
    assignee_membership_id: uuid.UUID | None,
    data: dict[str, Any],
    expected_updated_at: datetime | None,
) -> None:
    transition = TRANSITIONS[action]
    values: dict[str, Any] = {
        "status": transition.to_status,
        "assignee_membership_id": assignee_membership_id,
        **_ENTRY_TIMESTAMPS.get(transition.to_status, {}),
    }
    if not await _compare_and_set(session, request, values, expected_updated_at=expected_updated_at):
        raise ConcurrentChangeError
    record_event(
        session,
        request,
        actor_membership_id=membership.id,
        event_type=transition.event_type,
        from_status=request.status,
        to_status=transition.to_status,
        data=data,
    )


async def _set_priority(
    session: AsyncSession,
    request: Request,
    membership: Membership,
    priority: RequestPriority,
    *,
    data: dict[str, Any],
    expected_updated_at: datetime | None,
) -> None:
    values = {"priority": priority}
    if not await _compare_and_set(
        session, request, values, guard_priority=True, expected_updated_at=expected_updated_at
    ):
        raise ConcurrentChangeError
    record_event(
        session,
        request,
        actor_membership_id=membership.id,
        event_type=RequestEventType.PRIORITY_CHANGED,
        data={"from_priority": request.priority.value, "to_priority": priority.value, **data},
    )


async def validate(session: AsyncSession, request: Request, actor: Actor, change: Change) -> None:
    """Would this change be allowed right now? Raises the reason if not; writes nothing.
    Used to preview proposals: stage() re-checks everything when it actually runs."""
    check(change.action, request, actor)
    if change.action == RequestAction.ASSIGN:
        assert change.assignee_membership_id is not None
        await _validate_assignee(session, request, change.assignee_membership_id)


async def stage(
    session: AsyncSession,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    membership: Membership,
    change: Change,
    *,
    expected_updated_at: datetime | None = None,
    event_data: dict[str, Any] | None = None,
) -> None:
    """Authorize and apply one action inside the CALLER's transaction: no commit.

    The per-action endpoints commit right after (see perform); an approved AI proposal
    stages several and commits once, so they all happen or none do. With
    `expected_updated_at`, any change since the request was reviewed → 409 (stale).
    `event_data` is added to the history event (e.g. which approval caused it).
    """
    request = await _authorize(session, organization_id, request_id, membership, change.action)  # 404/403/409
    if expected_updated_at is not None and request.updated_at != expected_updated_at:
        raise StaleRequestError
    extra = event_data or {}
    common = dict(data=extra, expected_updated_at=expected_updated_at)
    match change.action:
        case RequestAction.ASSIGN:
            assert change.assignee_membership_id is not None
            if request.assignee_membership_id == change.assignee_membership_id:
                return  # Idempotent: already assigned to this person (a retry, or a double click).
            assignee_name = await _validate_assignee(session, request, change.assignee_membership_id)
            data = {
                "assignee_membership_id": str(change.assignee_membership_id),
                "assignee_name": assignee_name,
                "previous_assignee_membership_id": (
                    str(request.assignee_membership_id) if request.assignee_membership_id else None
                ),
                **extra,
            }
            await _apply(
                session, request, membership, change.action,
                assignee_membership_id=change.assignee_membership_id,
                data=data, expected_updated_at=expected_updated_at,
            )
        case RequestAction.CLAIM:
            data = {"assignee_membership_id": str(membership.id), "claimed": True, **extra}
            await _apply(
                session, request, membership, change.action,
                assignee_membership_id=membership.id, data=data, expected_updated_at=expected_updated_at,
            )
        case RequestAction.UNASSIGN:
            data = {"previous_assignee_membership_id": str(request.assignee_membership_id), **extra}
            await _apply(
                session, request, membership, change.action,
                assignee_membership_id=None, data=data, expected_updated_at=expected_updated_at,
            )
        case RequestAction.CHANGE_PRIORITY:
            assert change.priority is not None
            if request.priority == change.priority:
                return  # Idempotent, like assigning the same person.
            await _set_priority(session, request, membership, change.priority, **common)
        case _:  # START, COMPLETE, CANCEL keep the assignee
            await _apply(
                session, request, membership, change.action,
                assignee_membership_id=request.assignee_membership_id, **common,
            )


async def perform(
    session: AsyncSession,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    membership: Membership,
    change: Change,
) -> RequestRow:
    """One action as its own transaction: the request + its history event, both or neither."""
    try:
        await stage(session, organization_id, request_id, membership, change)
    except DomainError:
        await session.rollback()
        raise
    await session.commit()
    return await get_request(session, organization_id, request_id, viewer_for(membership))


async def assign(
    session: AsyncSession,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    membership: Membership,
    assignee_membership_id: uuid.UUID,
) -> RequestRow:
    change = Change(RequestAction.ASSIGN, assignee_membership_id=assignee_membership_id)
    return await perform(session, organization_id, request_id, membership, change)


async def claim(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, membership: Membership
) -> RequestRow:
    return await perform(session, organization_id, request_id, membership, Change(RequestAction.CLAIM))


async def unassign(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, membership: Membership
) -> RequestRow:
    return await perform(session, organization_id, request_id, membership, Change(RequestAction.UNASSIGN))


async def start(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, membership: Membership
) -> RequestRow:
    return await perform(session, organization_id, request_id, membership, Change(RequestAction.START))


async def complete(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, membership: Membership
) -> RequestRow:
    return await perform(session, organization_id, request_id, membership, Change(RequestAction.COMPLETE))


async def cancel(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, membership: Membership
) -> RequestRow:
    return await perform(session, organization_id, request_id, membership, Change(RequestAction.CANCEL))


async def change_priority(
    session: AsyncSession,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    membership: Membership,
    priority: RequestPriority,
) -> RequestRow:
    change = Change(RequestAction.CHANGE_PRIORITY, priority=priority)
    return await perform(session, organization_id, request_id, membership, change)
