"""Request use cases. Every query is scoped by organization_id, and reads apply
the viewer's visibility (members only see requests they created)."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, Select, func, select, true, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.departments.models import Department
from app.errors import NotFoundError, UnprocessableError
from app.organizations.models import Membership
from app.pagination import KeysetCursor
from app.permissions import Permission, has_permission
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


def viewer_for(membership: Membership) -> Viewer:
    return Viewer(
        membership_id=membership.id,
        can_read_all=has_permission(membership.role, Permission.REQUESTS_READ_ALL),
    )


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
            _request_rows(organization_id)
            .where(Request.id == request_id, _visible_to(viewer))
            # Refresh a Request already in the identity map (e.g. after a lifecycle UPDATE).
            .execution_options(populate_existing=True)
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


@dataclass(frozen=True)
class RequestFilters:
    """What to match. Filters combine with AND; list and count share them, so a count
    always describes exactly the rows a list would page through."""

    statuses: list[RequestStatus] | None = None
    department_id: uuid.UUID | None = None
    priorities: list[RequestPriority] | None = None
    assignee_membership_id: uuid.UUID | None = None
    unassigned: bool = False
    requester_membership_id: uuid.UUID | None = None
    title_contains: str | None = None
    created_within: timedelta | None = None

    def __post_init__(self) -> None:
        if self.unassigned and self.assignee_membership_id is not None:
            raise ValueError("Filter by an assignee or by unassigned, not both")

    def conditions(self) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if self.statuses:
            conditions.append(Request.status.in_(self.statuses))
        if self.department_id is not None:
            conditions.append(Request.department_id == self.department_id)
        if self.priorities:
            conditions.append(Request.priority.in_(self.priorities))
        if self.assignee_membership_id is not None:
            conditions.append(Request.assignee_membership_id == self.assignee_membership_id)
        if self.unassigned:
            conditions.append(Request.assignee_membership_id.is_(None))
        if self.requester_membership_id is not None:
            conditions.append(Request.requester_membership_id == self.requester_membership_id)
        if self.title_contains:
            # autoescape: "%" and "_" in the search text match literally, not as wildcards.
            # Unindexed substring scan: fine at V1 scale (pg_trgm if it ever isn't).
            conditions.append(Request.title.icontains(self.title_contains, autoescape=True))
        if self.created_within is not None:
            conditions.append(Request.created_at >= func.now() - self.created_within)  # DB clock
        return conditions


async def list_requests(
    session: AsyncSession,
    organization_id: uuid.UUID,
    viewer: Viewer,
    filters: RequestFilters,
    *,
    limit: int,
    after: KeysetCursor | None,
) -> tuple[list[RequestRow], KeysetCursor | None]:
    """Newest first. Returns one page plus the cursor for the next page (None at the end).
    Visibility and the organization scope always apply."""
    query = _request_rows(organization_id).where(_visible_to(viewer), *filters.conditions())
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


async def count_requests(
    session: AsyncSession, organization_id: uuid.UUID, viewer: Viewer, filters: RequestFilters
) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Request)
        .where(Request.organization_id == organization_id, _visible_to(viewer), *filters.conditions())
    )
    return count or 0


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


async def request_titles(
    session: AsyncSession, organization_id: uuid.UUID, viewer: Viewer, request_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Titles of the given requests that exist in this org and are visible to the viewer."""
    if not request_ids:
        return {}
    result = await session.execute(
        select(Request.id, Request.title).where(
            Request.organization_id == organization_id,
            Request.id.in_(request_ids),
            _visible_to(viewer),
        )
    )
    return {request_id: title for request_id, title in result}
