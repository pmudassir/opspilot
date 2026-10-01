"""lifecycle.stage(): several actions in ONE caller-owned transaction (used by approved
AI proposals). Nothing is committed by stage itself: all or nothing."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError
from app.organizations.models import Membership
from app.requests import lifecycle
from app.requests.lifecycle import Change, RequestAction, StaleRequestError
from app.requests.models import Request, RequestEvent, RequestPriority, RequestStatus
from tests.helpers import (
    add_member_id,
    create_department_id,
    create_request_id,
    logged_in,
    signup_org,
)


@dataclass(frozen=True)
class World:
    org_id: uuid.UUID
    manager_id: uuid.UUID
    requests: list[uuid.UUID]


@pytest.fixture
async def world(make_client: Callable[..., AsyncClient]) -> World:
    admin = make_client()
    org_id = await signup_org(admin, email="alice@a.example", organization_name="Hotel A")
    manager_id = await add_member_id(admin, org_id, email="manager@a.example", role="manager")
    await add_member_id(admin, org_id, email="mia@a.example", role="member")
    mia = await logged_in(make_client(), "mia@a.example")
    it = await create_department_id(admin, org_id, "IT")
    requests = [uuid.UUID(await create_request_id(mia, org_id, it, title=f"r{n}")) for n in range(3)]
    return World(uuid.UUID(org_id), uuid.UUID(manager_id), requests)


async def manager(db: AsyncSession, world: World) -> Membership:
    membership = await db.scalar(select(Membership).where(Membership.id == world.manager_id))
    assert membership is not None
    return membership


async def statuses(db: AsyncSession, world: World) -> list[RequestStatus]:
    db.expire_all()
    rows = await db.scalars(select(Request.status).where(Request.id.in_(world.requests)).order_by(Request.title))
    return list(rows)


async def test_staged_changes_commit_together(db_session: AsyncSession, world: World) -> None:
    me = await manager(db_session, world)
    for request_id in world.requests:
        await lifecycle.stage(db_session, world.org_id, request_id, me, Change(RequestAction.CANCEL), event_data={"approval_id": "a1"})
    await db_session.commit()
    assert await statuses(db_session, world) == [RequestStatus.CANCELLED] * 3
    events = (await db_session.scalars(select(RequestEvent).where(RequestEvent.event_type == "status_changed"))).all()
    assert len(events) == 3 and all(e.data == {"approval_id": "a1"} for e in events)


async def test_one_failure_means_nothing_changes(db_session: AsyncSession, world: World) -> None:
    me = await manager(db_session, world)
    await db_session.execute(text("UPDATE requests SET status = 'cancelled', cancelled_at = now() WHERE id = :id"), {"id": world.requests[2]})
    await db_session.commit()
    with pytest.raises(ConflictError):
        for request_id in world.requests:  # the third is already cancelled → 409
            await lifecycle.stage(db_session, world.org_id, request_id, me, Change(RequestAction.CANCEL))
    await db_session.rollback()
    assert await statuses(db_session, world) == [RequestStatus.OPEN, RequestStatus.OPEN, RequestStatus.CANCELLED]


async def test_expected_version_detects_any_change_since_the_preview(db_session: AsyncSession, world: World) -> None:
    me = await manager(db_session, world)
    seen = await db_session.scalar(select(Request.updated_at).where(Request.id == world.requests[0]))
    await db_session.execute(text("UPDATE requests SET title = 'edited', updated_at = now() + interval '1 second' WHERE id = :id"), {"id": world.requests[0]})
    await db_session.commit()
    with pytest.raises(StaleRequestError) as caught:
        await lifecycle.stage(db_session, world.org_id, world.requests[0], me, Change(RequestAction.CANCEL), expected_updated_at=seen)
    assert caught.value.status_code == 409


async def test_staged_priority_change(db_session: AsyncSession, world: World) -> None:
    me = await manager(db_session, world)
    seen = await db_session.scalar(select(Request.updated_at).where(Request.id == world.requests[0]))
    await lifecycle.stage(
        db_session, world.org_id, world.requests[0], me, Change(RequestAction.CHANGE_PRIORITY, priority=RequestPriority.HIGH),
        expected_updated_at=seen,
    )
    await db_session.commit()
    db_session.expire_all()
    request = await db_session.scalar(select(Request).where(Request.id == world.requests[0]))
    assert request is not None and request.priority == RequestPriority.HIGH
    assert request.updated_at - seen < timedelta(minutes=1)
