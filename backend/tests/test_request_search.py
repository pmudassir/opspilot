"""Service-level search filters and department staff (used by the AI tools, Phase 5).
Data is set up through the HTTP API; the service functions are called directly."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.departments.service import list_department_staff
from app.errors import NotFoundError
from app.requests.models import RequestPriority, RequestStatus
from app.requests.service import RequestFilters, Viewer, count_requests, list_requests
from tests.helpers import (
    act,
    add_member_id,
    create_department_id,
    create_request_id,
    logged_in,
    org_url,
    signup_org,
)


@dataclass(frozen=True)
class World:
    org_id: uuid.UUID
    ids: dict[str, uuid.UUID]  # membership ids by name
    it: uuid.UUID
    housekeeping: uuid.UUID
    requests: dict[str, uuid.UUID]  # request ids by title
    other_org_it: uuid.UUID


@pytest.fixture
async def world(make_client: Callable[..., AsyncClient], db_session: AsyncSession) -> World:
    admin = make_client()
    org_id = await signup_org(admin, email="alice@a.example", organization_name="Hotel A")
    roles = {"agent": "agent", "agent2": "agent", "gone": "agent", "manager": "manager", "mia": "member", "max": "member"}
    ids = {name: await add_member_id(admin, org_id, email=f"{name}@a.example", role=role) for name, role in roles.items()}
    it = await create_department_id(admin, org_id, "IT")
    housekeeping = await create_department_id(admin, org_id, "Housekeeping")
    for name, department in [("agent", it), ("agent2", it), ("gone", it), ("manager", it), ("mia", it), ("agent2", housekeeping)]:
        assert (await admin.put(org_url(org_id, f"/departments/{department}/members/{ids[name]}"))).status_code == 204
    mia = await logged_in(make_client(), "mia@a.example")
    max_ = await logged_in(make_client(), "max@a.example")
    agent = await logged_in(make_client(), "agent@a.example")

    requests = {}
    for title, client, department in [
        ("Printer jammed", mia, it),
        ("Wi-Fi drops in lobby", mia, it),
        ("100% CPU on the kiosk", max_, it),
        ("Old laptop request", mia, it),
        ("Extra towels", mia, housekeeping),
        ("Finished printer ticket", mia, it),
    ]:
        requests[title] = uuid.UUID(await create_request_id(client, org_id, department, title=title))

    def assign(name: str) -> dict[str, str]:
        return {"assignee_membership_id": ids[name]}

    r = {k: str(v) for k, v in requests.items()}
    await act(admin, org_id, r["Printer jammed"], "assign", assign("agent"))
    await act(admin, org_id, r["Wi-Fi drops in lobby"], "assign", assign("agent"))
    await act(agent, org_id, r["Wi-Fi drops in lobby"], "start")
    await act(admin, org_id, r["Extra towels"], "assign", assign("agent2"))
    await act(admin, org_id, r["Finished printer ticket"], "assign", assign("agent"))
    await act(agent, org_id, r["Finished printer ticket"], "start")
    await act(agent, org_id, r["Finished printer ticket"], "complete")
    await act(admin, org_id, r["100% CPU on the kiosk"], "assign", assign("gone"))
    assert (await admin.patch(org_url(org_id, f"/members/{ids['gone']}"), json={"status": "deactivated"})).status_code == 200
    await db_session.execute(
        text("UPDATE requests SET created_at = now() - interval '40 days' WHERE id = :id"),
        {"id": requests["Old laptop request"]},
    )
    await db_session.commit()

    # Another organization with look-alike data must never show up.
    other = make_client()
    other_org = await signup_org(other, email="bob@b.example", organization_name="Hotel B")
    other_it = await create_department_id(other, other_org, "IT")
    await create_request_id(other, other_org, other_it, title="Printer jammed")

    return World(
        uuid.UUID(org_id),
        {name: uuid.UUID(value) for name, value in ids.items()},
        uuid.UUID(it),
        uuid.UUID(housekeeping),
        requests,
        uuid.UUID(other_it),
    )


def staff_viewer(world: World) -> Viewer:
    return Viewer(membership_id=world.ids["manager"], can_read_all=True)


async def titles(db: AsyncSession, world: World, viewer: Viewer | None = None, **filters: Any) -> set[str]:
    rows, _ = await list_requests(
        db, world.org_id, viewer or staff_viewer(world), RequestFilters(**filters), limit=50, after=None
    )
    return {row.request.title for row in rows}


# --- list_requests filters ----------------------------------------------------


async def test_filter_by_assignee(db_session: AsyncSession, world: World) -> None:
    assert await titles(db_session, world, assignee_membership_id=world.ids["agent"]) == {
        "Printer jammed",
        "Wi-Fi drops in lobby",
        "Finished printer ticket",
    }


async def test_filter_unassigned(db_session: AsyncSession, world: World) -> None:
    assert await titles(db_session, world, unassigned=True) == {"Old laptop request"}


def test_assignee_and_unassigned_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError):
        RequestFilters(assignee_membership_id=uuid.uuid4(), unassigned=True)


async def test_filter_by_several_priorities(db_session: AsyncSession, world: World) -> None:
    await db_session.execute(
        text("UPDATE requests SET priority = 'urgent' WHERE id = :id"), {"id": world.requests["Printer jammed"]}
    )
    await db_session.execute(
        text("UPDATE requests SET priority = 'high' WHERE id = :id"), {"id": world.requests["Extra towels"]}
    )
    await db_session.commit()
    assert await titles(db_session, world, priorities=[RequestPriority.URGENT, RequestPriority.HIGH]) == {
        "Printer jammed",
        "Extra towels",
    }


async def test_count_uses_the_same_filters_visibility_and_scope(db_session: AsyncSession, world: World) -> None:
    printers = RequestFilters(title_contains="printer")
    assert await count_requests(db_session, world.org_id, staff_viewer(world), printers) == 2  # org B's excluded
    max_viewer = Viewer(membership_id=world.ids["max"], can_read_all=False)
    assert await count_requests(db_session, world.org_id, max_viewer, printers) == 0
    assert await count_requests(db_session, world.org_id, staff_viewer(world), RequestFilters()) == 6


async def test_filter_by_requester(db_session: AsyncSession, world: World) -> None:
    assert await titles(db_session, world, requester_membership_id=world.ids["max"]) == {"100% CPU on the kiosk"}


async def test_title_contains_is_case_insensitive(db_session: AsyncSession, world: World) -> None:
    assert await titles(db_session, world, title_contains="PRINTER") == {"Printer jammed", "Finished printer ticket"}


@pytest.mark.parametrize(("needle", "expected"), [("%", {"100% CPU on the kiosk"}), ("_", set())])
async def test_title_contains_treats_wildcards_literally(
    db_session: AsyncSession, world: World, needle: str, expected: set[str]
) -> None:
    assert await titles(db_session, world, title_contains=needle) == expected


async def test_created_within_uses_the_database_clock(db_session: AsyncSession, world: World) -> None:
    recent = await titles(db_session, world, created_within=timedelta(days=30))
    assert "Old laptop request" not in recent
    assert len(recent) == 5


async def test_filters_combine(db_session: AsyncSession, world: World) -> None:
    assert await titles(
        db_session,
        world,
        assignee_membership_id=world.ids["agent"],
        statuses=[RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS],
        title_contains="printer",
    ) == {"Printer jammed"}


async def test_filters_keep_member_visibility(db_session: AsyncSession, world: World) -> None:
    max_viewer = Viewer(membership_id=world.ids["max"], can_read_all=False)
    assert await titles(db_session, world, max_viewer, title_contains="printer") == set()
    assert await titles(db_session, world, max_viewer, title_contains="cpu") == {"100% CPU on the kiosk"}


async def test_filters_stay_inside_the_organization(db_session: AsyncSession, world: World) -> None:
    # Org B also has a "Printer jammed" request; only org A's show up.
    rows, _ = await list_requests(
        db_session, world.org_id, staff_viewer(world), RequestFilters(title_contains="jammed"), limit=50, after=None
    )
    assert [row.request.organization_id for row in rows] == [world.org_id]


# --- list_department_staff ----------------------------------------------------


async def test_department_staff_with_open_workload(db_session: AsyncSession, world: World) -> None:
    staff = await list_department_staff(db_session, world.org_id, world.it)
    # Active staff only: "mia" (member role) and "gone" (deactivated) are excluded.
    # Workload counts assigned + in progress, not completed; least busy first.
    assert [(s.full_name, s.role.value, s.open_assignments) for s in staff] == [
        ("Manager", "manager", 0),
        ("Agent2", "agent", 1),
        ("Agent", "agent", 2),
    ]


async def test_department_staff_counts_work_across_all_departments(db_session: AsyncSession, world: World) -> None:
    # agent2's one assignment is in Housekeeping; it still counts towards their load.
    staff = {s.full_name: s.open_assignments for s in await list_department_staff(db_session, world.org_id, world.it)}
    assert staff["Agent2"] == 1


async def test_department_staff_of_another_org_is_not_found(db_session: AsyncSession, world: World) -> None:
    with pytest.raises(NotFoundError):
        await list_department_staff(db_session, world.org_id, world.other_org_it)
