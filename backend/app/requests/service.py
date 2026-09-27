"""Request use cases. Every query is scoped by organization_id, and reads apply
the viewer's visibility (members only see requests they created)."""

import uuid
from dataclasses import dataclass
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, Select, select, true, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.departments.models import Department
from app.errors import NotFoundError, UnprocessableError
from app.organizations.models import Membership
from app.pagination import KeysetCursor
from app.requests.models import (
    Request,
    RequestEvent,
    RequestEventType,
    RequestPriority,
    RequestStatus,
)
from app.users.models import User


@dataclass(frozen=True)
class Viewer:
    membership_id: uuid.UUID
    can_read_all: bool


class RequestRow(NamedTuple):
    request: Request
    department_name: str
    requester_name: str
    assignee_name: str | None


class EventRow(NamedTuple):
    event: RequestEvent
    actor_name: str


_Requester = aliased(Membership, name="requester")
_RequesterUser = aliased(User, name="requester_user")
_Assignee = aliased(Membership, name="assignee")
_AssigneeUser = aliased(User, name="assignee_user")


def _request_rows(organization_id: uuid.UUID) -> Select[Any]:
    """Requests of one organization joined with display names. Joins also match on
    organization_id, mirroring the composite foreign keys."""
    return (
        select(Request, Department.name, _RequesterUser.full_name, _AssigneeUser.full_name)
        .join(
            Department,
            (Department.organization_id == Request.organization_id)
            & (Department.id == Request.department_id),
        )
        .join(
            _Requester,
            (_Requester.organization_id == Request.organization_id)
            & (_Requester.id == Request.requester_membership_id),
        )
        .join(_RequesterUser, _RequesterUser.id == _Requester.user_id)
        .outerjoin(
            _Assignee,
            (_Assignee.organization_id == Request.organization_id)
            & (_Assignee.id == Request.assignee_membership_id),
        )
        .outerjoin(_AssigneeUser, _AssigneeUser.id == _Assignee.user_id)
        .where(Request.organization_id == organization_id)
    )


def _visible_to(viewer: Viewer) -> ColumnElement[bool]:
    if viewer.can_read_all:
        return true()
    return Request.requester_membership_id == viewer.membership_id


def record_event(
    session: AsyncSession,
    request: Request,
    *,
    actor_membership_id: uuid.UUID,
    event_type: RequestEventType,
    from_status: RequestStatus | None = None,
    to_status: RequestStatus | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Add a history event to the caller's transaction (committed with the change itself)."""
    session.add(
        RequestEvent(
            organization_id=request.organization_id,
            request_id=request.id,
            actor_membership_id=actor_membership_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            data=data or {},
        )
    )


async def _get_row(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, viewer: Viewer
) -> RequestRow:
    row = (
        await session.execute(
            _request_rows(organization_id).where(Request.id == request_id, _visible_to(viewer))
        )
    ).first()
    if row is None:
        # Invisible and nonexistent look the same: don't reveal other people's requests.
        raise NotFoundError("Request")
    return RequestRow(*row)


async def create_request(
    session: AsyncSession,
    organization_id: uuid.UUID,
    *,
    requester_membership_id: uuid.UUID,
    department_id: uuid.UUID,
    title: str,
    description: str,
    priority: RequestPriority,
) -> RequestRow:
    department_exists = await session.scalar(
        select(Department.id).where(
            Department.organization_id == organization_id, Department.id == department_id
        )
    )
    if department_exists is None:
        raise UnprocessableError("Department not found")

    request = Request(
        organization_id=organization_id,
        department_id=department_id,
        requester_membership_id=requester_membership_id,
        title=title,
        description=description,
        priority=priority,
    )
    session.add(request)
    await session.flush()  # assigns request.id for the event
    record_event(
        session,
        request,
        actor_membership_id=requester_membership_id,
        event_type=RequestEventType.CREATED,
        to_status=RequestStatus.OPEN,
    )
    await session.commit()  # request + its "created" event: both or neither
    creator = Viewer(membership_id=requester_membership_id, can_read_all=False)
    return await _get_row(session, organization_id, request.id, creator)


async def get_request(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, viewer: Viewer
) -> RequestRow:
    return await _get_row(session, organization_id, request_id, viewer)


async def list_requests(
    session: AsyncSession,
    organization_id: uuid.UUID,
    viewer: Viewer,
    *,
    statuses: list[RequestStatus] | None,
    department_id: uuid.UUID | None,
    priority: RequestPriority | None,
    limit: int,
    after: KeysetCursor | None,
) -> tuple[list[RequestRow], KeysetCursor | None]:
    """Newest first. Returns one page plus the cursor for the next page (None at the end)."""
    query = _request_rows(organization_id).where(_visible_to(viewer))
    if statuses:
        query = query.where(Request.status.in_(statuses))
    if department_id is not None:
        query = query.where(Request.department_id == department_id)
    if priority is not None:
        query = query.where(Request.priority == priority)
    if after is not None:
        query = query.where(tuple_(Request.created_at, Request.id) < (after.created_at, after.id))

    # Fetch one extra row to learn whether another page exists.
    result = await session.execute(
        query.order_by(Request.created_at.desc(), Request.id.desc()).limit(limit + 1)
    )
    rows = [RequestRow(*row) for row in result]
    page, has_more = rows[:limit], len(rows) > limit
    next_cursor = (
        KeysetCursor(page[-1].request.created_at, page[-1].request.id) if has_more else None
    )
    return page, next_cursor


async def list_events(
    session: AsyncSession, organization_id: uuid.UUID, request_id: uuid.UUID, viewer: Viewer
) -> list[EventRow]:
    await _get_row(session, organization_id, request_id, viewer)  # visibility check / 404
    actor = aliased(Membership)
    result = await session.execute(
        select(RequestEvent, User.full_name)
        .join(
            actor,
            (actor.organization_id == RequestEvent.organization_id)
            & (actor.id == RequestEvent.actor_membership_id),
        )
        .join(User, User.id == actor.user_id)
        .where(
            RequestEvent.organization_id == organization_id,
            RequestEvent.request_id == request_id,
        )
        .order_by(RequestEvent.created_at, RequestEvent.id)
    )
    return [EventRow(*row) for row in result]
