import asyncio
import contextlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.requests import lifecycle
from tests.helpers import (
    act,
    add_member_id,
    create_department_id,
    create_request_id,
    logged_in,
    org_url,
    signup_org,
)

RENDEZVOUS_TIMEOUT_SECONDS = 0.5
STAFF = {"manager": "manager", "agent": "agent", "agent2": "agent", "hk_agent": "agent"}
MEMBERS = {"mia": "member", "max": "member"}


@dataclass(frozen=True)
class Team:
    """Hotel A: manager, agent and agent2 work in IT; hk_agent works in Housekeeping.
    Mia (member) has reported one OPEN request in IT."""

    org_id: str
    admin: AsyncClient
    clients: dict[str, AsyncClient]
    ids: dict[str, str]  # membership ids by name
    request_id: str

    async def act(self, who: str, action: str, **body: str) -> Response:
        client = self.admin if who == "admin" else self.clients[who]
        return await act(client, self.org_id, self.request_id, action, body or None)

    async def assign(self, who: str, assignee: str) -> Response:
        return await self.act(who, "assign", assignee_membership_id=self.ids[assignee])

    async def request(self) -> dict[str, Any]:
        response = await self.admin.get(org_url(self.org_id, f"/requests/{self.request_id}"))
        return response.json()

    async def events(self) -> list[dict[str, Any]]:
        url = org_url(self.org_id, f"/requests/{self.request_id}/events")
        return (await self.admin.get(url)).json()


@pytest.fixture
async def team(make_client: Callable[[], AsyncClient]) -> Team:
    admin = make_client()
    org_id = await signup_org(admin, email="alice@a.example", organization_name="Hotel A")
    ids = {
        name: await add_member_id(admin, org_id, email=f"{name}@a.example", role=role)
        for name, role in {**STAFF, **MEMBERS}.items()
    }
    it = await create_department_id(admin, org_id, "IT")
    housekeeping = await create_department_id(admin, org_id, "Housekeeping")
    for name, department in [
        ("manager", it),
        ("agent", it),
        ("agent2", it),
        ("hk_agent", housekeeping),
    ]:
        url = org_url(org_id, f"/departments/{department}/members/{ids[name]}")
        assert (await admin.put(url)).status_code == 204
    clients = {name: await logged_in(make_client(), f"{name}@a.example") for name in ids}
    request_id = await create_request_id(clients["mia"], org_id, it)
    return Team(org_id, admin, clients, ids, request_id)


# --- happy path ---------------------------------------------------------------


async def test_full_lifecycle_updates_status_timestamps_and_timeline(team: Team) -> None:
    assigned = await team.assign("manager", "agent")
    started = await team.act("agent", "start")
    completed = await team.act("agent", "complete")

    assert [r.status_code for r in (assigned, started, completed)] == [200, 200, 200]
    body = completed.json()
    assert body["status"] == "completed"
    assert body["assignee"]["membership_id"] == team.ids["agent"]
    assert body["assigned_at"] <= body["started_at"] <= body["completed_at"]
    assert body["cancelled_at"] is None

    events = await team.events()
    assert [(e["event_type"], e["from_status"], e["to_status"], e["actor"]["full_name"]) for e in events] == [
        ("created", None, "open", "Mia"),
        ("assigned", "open", "assigned", "Manager"),
        ("status_changed", "assigned", "in_progress", "Agent"),
        ("status_changed", "in_progress", "completed", "Agent"),
    ]
    assert events[1]["data"]["assignee_name"] == "Agent"


async def test_agent_claims_open_request_in_own_department(team: Team) -> None:
    response = await team.act("agent", "claim")

    assert response.status_code == 200
    assert response.json()["status"] == "assigned"
    assert response.json()["assignee"]["membership_id"] == team.ids["agent"]
    assert (await team.events())[-1]["data"]["claimed"] is True


# --- claim rules --------------------------------------------------------------


@pytest.mark.parametrize("who", ["hk_agent", "mia"])
async def test_claim_is_forbidden_outside_department_or_for_members(team: Team, who: str) -> None:
    assert (await team.act(who, "claim")).status_code == 403


async def test_cannot_claim_already_assigned_request(team: Team) -> None:
    await team.assign("manager", "agent")

    assert (await team.act("agent2", "claim")).status_code == 409


# --- assign rules -------------------------------------------------------------


@pytest.mark.parametrize(
    ("assignee", "detail"),
    [
        ("mia", "Assignee must be staff (agent, manager or admin)"),
        ("hk_agent", "Assignee must belong to the request's department"),
        ("random", "Assignee not found"),
    ],
)
async def test_assignee_must_be_staff_in_the_department(
    team: Team, assignee: str, detail: str
) -> None:
    target = str(uuid.uuid4()) if assignee == "random" else team.ids[assignee]

    response = await team.act("manager", "assign", assignee_membership_id=target)

    assert response.status_code == 422
    assert response.json()["detail"] == detail


async def test_cannot_assign_to_deactivated_member(team: Team) -> None:
    url = org_url(team.org_id, f"/members/{team.ids['agent2']}")
    await team.admin.patch(url, json={"status": "deactivated"})

    response = await team.assign("manager", "agent2")

    assert response.status_code == 422
    assert response.json()["detail"] == "Assignee is deactivated"


@pytest.mark.parametrize("who", ["agent", "mia"])
async def test_only_supervisors_can_assign(team: Team, who: str) -> None:
    assert (await team.assign(who, "agent")).status_code == 403


async def test_assigning_the_current_assignee_again_is_idempotent(team: Team) -> None:
    first = await team.assign("manager", "agent")
    retry = await team.assign("manager", "agent")

    assert first.status_code == retry.status_code == 200
    assert [e["event_type"] for e in await team.events()] == ["created", "assigned"]


async def test_reassigning_in_progress_work_returns_it_to_assigned(team: Team) -> None:
    await team.assign("manager", "agent")
    first_assigned_at = (await team.request())["assigned_at"]
    await team.act("agent", "start")

    response = await team.assign("manager", "agent2")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "assigned"
    assert body["assignee"]["membership_id"] == team.ids["agent2"]
    # First-assignment and first-start times are kept for response-time metrics.
    assert body["assigned_at"] == first_assigned_at
    assert body["started_at"] is not None
    assert (await team.events())[-1]["data"]["previous_assignee_membership_id"] == team.ids["agent"]


async def test_unassign_returns_request_to_open(team: Team) -> None:
    await team.assign("manager", "agent")

    response = await team.act("manager", "unassign")

    assert response.status_code == 200
    assert response.json()["status"] == "open"
    assert response.json()["assignee"] is None
    assert (await team.events())[-1]["event_type"] == "unassigned"


async def test_agents_cannot_unassign(team: Team) -> None:
    await team.assign("manager", "agent")

    assert (await team.act("agent", "unassign")).status_code == 403


# --- start / complete ---------------------------------------------------------


async def test_only_the_assignee_agent_can_start(team: Team) -> None:
    await team.assign("manager", "agent")

    assert (await team.act("agent2", "start")).status_code == 403
    assert (await team.act("mia", "start")).status_code == 403


async def test_manager_can_start_on_behalf_of_assignee(team: Team) -> None:
    await team.assign("manager", "agent")

    response = await team.act("manager", "start")

    assert response.status_code == 200
    assert response.json()["assignee"]["membership_id"] == team.ids["agent"]


async def test_cannot_complete_work_that_has_not_started(team: Team) -> None:
    await team.assign("manager", "agent")

    response = await team.act("agent", "complete")

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot complete a request that is assigned"


# --- cancel -------------------------------------------------------------------


async def test_requester_cancels_own_open_request(team: Team) -> None:
    response = await team.act("mia", "cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["cancelled_at"] is not None


async def test_requester_cannot_cancel_once_work_is_assigned(team: Team) -> None:
    await team.assign("manager", "agent")

    assert (await team.act("mia", "cancel")).status_code == 403


async def test_other_members_cannot_see_let_alone_cancel(team: Team) -> None:
    assert (await team.act("max", "cancel")).status_code == 404


async def test_agents_cannot_cancel_others_requests(team: Team) -> None:
    assert (await team.act("agent", "cancel")).status_code == 403


async def test_manager_cancels_in_progress_work_and_assignee_is_kept(team: Team) -> None:
    await team.assign("manager", "agent")
    await team.act("agent", "start")

    response = await team.act("manager", "cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["assignee"]["membership_id"] == team.ids["agent"]


@pytest.mark.parametrize("terminal", ["completed", "cancelled"])
@pytest.mark.parametrize("action", ["assign", "claim", "unassign", "start", "complete", "cancel"])
async def test_terminal_requests_accept_no_further_actions(
    team: Team, terminal: str, action: str
) -> None:
    await team.assign("manager", "agent")
    if terminal == "completed":
        await team.act("agent", "start")
        await team.act("agent", "complete")
    else:
        await team.act("manager", "cancel")

    body = {"assignee_membership_id": team.ids["agent2"]} if action == "assign" else {}
    response = await team.act("admin", action, **body)

    assert response.status_code == 409


# --- concurrency --------------------------------------------------------------


@pytest.fixture
def force_concurrent_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make both requests read the same snapshot before either writes.

    Each compare-and-set waits until the other request has also passed all of its
    checks (or a short timeout). Without the WHERE guard, both UPDATEs would succeed
    and the second would silently overwrite the first (lost update).
    """
    original = lifecycle._compare_and_set
    arrived = 0
    both_arrived = asyncio.Event()

    async def rendezvous_then_compare_and_set(
        session: AsyncSession, request: Any, values: dict[str, Any]
    ) -> bool:
        nonlocal arrived
        arrived += 1
        if arrived >= 2:
            both_arrived.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(both_arrived.wait(), RENDEZVOUS_TIMEOUT_SECONDS)
        return await original(session, request, values)

    monkeypatch.setattr(lifecycle, "_compare_and_set", rendezvous_then_compare_and_set)


async def test_concurrent_claims_have_exactly_one_winner(
    team: Team, force_concurrent_writes: None
) -> None:
    responses = await asyncio.gather(team.act("agent", "claim"), team.act("agent2", "claim"))

    statuses = sorted(r.status_code for r in responses)
    winner = next(r for r in responses if r.status_code == 200).json()["assignee"]
    assert statuses == [200, 409]
    assert (await team.request())["assignee"] == winner
    assert [e["event_type"] for e in await team.events()] == ["created", "assigned"]


async def test_cancel_racing_assign_leaves_a_consistent_request(
    team: Team, force_concurrent_writes: None
) -> None:
    responses = await asyncio.gather(team.act("mia", "cancel"), team.assign("manager", "agent"))

    assert sorted(r.status_code for r in responses) == [200, 409]
    final = await team.request()
    events = await team.events()
    assert len(events) == 2  # created + exactly one of (cancelled, assigned)
    assert final["status"] == events[-1]["to_status"]
