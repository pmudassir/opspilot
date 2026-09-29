from collections.abc import Callable
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
class Scenario:
    org_id: str
    admin: AsyncClient
    clients: dict[str, AsyncClient]
    it: str
    housekeeping: str
    empty: str


async def set_times(db: AsyncSession, request_id: str, *, created_hours_ago: float, **offsets: float) -> None:
    """Pin created_at, and set <column> = created_at + <hours> for each given offset."""
    assignments = ", ".join(f"{column} = now() - make_interval(secs => :ago) + make_interval(secs => :{column})" for column in offsets)
    sql = f"UPDATE requests SET created_at = now() - make_interval(secs => :ago){', ' + assignments if assignments else ''} WHERE id = :id"
    params = {"id": request_id, "ago": created_hours_ago * 3600, **{k: v * 3600 for k, v in offsets.items()}}
    await db.execute(text(sql), params)
    await db.commit()


@pytest.fixture
async def scenario(make_client: Callable[..., AsyncClient], db_session: AsyncSession) -> Scenario:
    admin = make_client()
    org_id = await signup_org(admin, email="alice@a.example", organization_name="Hotel A")
    for name, role in [("agent", "agent"), ("manager", "manager"), ("member", "member")]:
        await add_member_id(admin, org_id, email=f"{name}@a.example", role=role)
    clients = {name: await logged_in(make_client(), f"{name}@a.example") for name in ("agent", "manager", "member")}
    members = (await admin.get(org_url(org_id, "/members"))).json()
    agent_id = next(m["membership_id"] for m in members if m["email"] == "agent@a.example")
    it = await create_department_id(admin, org_id, "IT")
    housekeeping = await create_department_id(admin, org_id, "Housekeeping")
    empty = await create_department_id(admin, org_id, "Security")
    await admin.put(org_url(org_id, f"/departments/{it}/members/{agent_id}"))
    assign = {"assignee_membership_id": agent_id}

    # IT: completed (assigned after 1h, done after 4h), in progress (2h), assigned (6h), open, old open
    r1 = await create_request_id(clients["member"], org_id, it, title="r1")
    await act(admin, org_id, r1, "assign", assign)
    await act(clients["agent"], org_id, r1, "start")
    await act(clients["agent"], org_id, r1, "complete")
    await set_times(db_session, r1, created_hours_ago=10, assigned_at=1, completed_at=4)
    r2 = await create_request_id(clients["member"], org_id, it, title="r2")
    await act(admin, org_id, r2, "assign", assign)
    await act(clients["agent"], org_id, r2, "start")
    await set_times(db_session, r2, created_hours_ago=10, assigned_at=2)
    r3 = await create_request_id(clients["member"], org_id, it, title="r3")
    await act(admin, org_id, r3, "assign", assign)
    await set_times(db_session, r3, created_hours_ago=10, assigned_at=6)
    r4 = await create_request_id(clients["member"], org_id, it, title="r4")
    await set_times(db_session, r4, created_hours_ago=10)
    r5 = await create_request_id(clients["member"], org_id, it, title="r5 (40 days old)")
    await set_times(db_session, r5, created_hours_ago=40 * 24)
    # Housekeeping: one cancelled
    r6 = await create_request_id(clients["member"], org_id, housekeeping, title="r6")
    await act(admin, org_id, r6, "cancel")

    # Another organization's data must never leak into these numbers.
    other = make_client()
    other_org = await signup_org(other, email="bob@b.example", organization_name="Hotel B")
    other_it = await create_department_id(other, other_org, "IT")
    for n in range(3):
        await create_request_id(other, other_org, other_it, title=f"b{n}")

    return Scenario(org_id, admin, clients, it, housekeeping, empty)


async def get_metrics(client: AsyncClient, org_id: str, days: int | None = None) -> dict:
    params = {"days": str(days)} if days else None
    response = await client.get(org_url(org_id, "/metrics"), params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_totals_count_backlog_and_period_flow(scenario: Scenario) -> None:
    totals = (await get_metrics(scenario.admin, scenario.org_id))["totals"]

    assert {k: totals[k] for k in ("open", "assigned", "in_progress")} == {"open": 2, "assigned": 1, "in_progress": 1}
    # r5 is 40 days old: in the backlog, but not "created in the last 30 days".
    assert totals["created_in_period"] == 5
    assert totals["completed_in_period"] == 1
    assert totals["cancelled_in_period"] == 1


async def test_time_to_assign_uses_median_and_p90(scenario: Scenario) -> None:
    it = next(d for d in (await get_metrics(scenario.admin, scenario.org_id))["departments"] if d["department_name"] == "IT")

    assert it["median_hours_to_assign"] == 2.0  # of 1h, 2h, 6h
    assert it["p90_hours_to_assign"] == 5.2  # interpolated: 2 + 0.8 × (6 − 2)
    assert it["median_hours_to_complete"] == 4.0
    assert it["p90_hours_to_complete"] == 4.0


async def test_every_department_is_listed_even_without_requests(scenario: Scenario) -> None:
    departments = {d["department_name"]: d for d in (await get_metrics(scenario.admin, scenario.org_id))["departments"]}

    assert list(departments) == ["Housekeeping", "IT", "Security"]
    security = departments["Security"]
    assert security["open"] == security["created_in_period"] == 0
    assert security["median_hours_to_assign"] is None
    housekeeping = departments["Housekeeping"]
    assert (housekeeping["created_in_period"], housekeeping["cancelled_in_period"]) == (1, 1)
    assert housekeeping["median_hours_to_complete"] is None


async def test_period_parameter_narrows_flow_but_not_backlog(scenario: Scenario) -> None:
    year = (await get_metrics(scenario.admin, scenario.org_id, days=365))["totals"]

    assert year["created_in_period"] == 6  # r5 now inside the period
    assert year["open"] == 2


@pytest.mark.parametrize(("who", "status"), [("manager", 200), ("agent", 403), ("member", 403)])
async def test_metrics_are_for_managers_and_admins(scenario: Scenario, who: str, status: int) -> None:
    response = await scenario.clients[who].get(org_url(scenario.org_id, "/metrics"))

    assert response.status_code == status


@pytest.mark.parametrize("days", ["0", "366", "soon"])
async def test_period_is_validated(scenario: Scenario, days: str) -> None:
    response = await scenario.admin.get(org_url(scenario.org_id, "/metrics"), params={"days": days})

    assert response.status_code == 422
