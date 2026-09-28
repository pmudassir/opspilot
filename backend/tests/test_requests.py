import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.requests import service as request_service
from app.requests.models import Request
from tests.helpers import (
    add_member_id,
    create_department_id,
    create_request,
    create_request_id,
    logged_in,
    org_url,
    signup_org,
)


@dataclass(frozen=True)
class Hotel:
    org_id: str
    admin: AsyncClient
    agent: AsyncClient
    mia: AsyncClient  # member
    max: AsyncClient  # member
    it: str
    housekeeping: str


@pytest.fixture
async def hotel(make_client: Callable[[], AsyncClient]) -> Hotel:
    admin = make_client()
    org_id = await signup_org(admin, email="alice@a.example", organization_name="Hotel A")
    await add_member_id(admin, org_id, email="agent@a.example", role="agent")
    await add_member_id(admin, org_id, email="mia@a.example", role="member")
    await add_member_id(admin, org_id, email="max@a.example", role="member")
    return Hotel(
        org_id=org_id,
        admin=admin,
        agent=await logged_in(make_client(), "agent@a.example"),
        mia=await logged_in(make_client(), "mia@a.example"),
        max=await logged_in(make_client(), "max@a.example"),
        it=await create_department_id(admin, org_id, "IT"),
        housekeeping=await create_department_id(admin, org_id, "Housekeeping"),
    )


def requests_url(hotel: Hotel, suffix: str = "") -> str:
    return org_url(hotel.org_id, f"/requests{suffix}")


# --- create -------------------------------------------------------------------


async def test_create_request_returns_open_unassigned_request(hotel: Hotel) -> None:
    response = await create_request(
        hotel.mia, hotel.org_id, hotel.it, title="  Wi-Fi drops in meeting room 2 ", priority="high"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Wi-Fi drops in meeting room 2"
    assert body["status"] == "open"
    assert body["priority"] == "high"
    assert body["assignee"] is None
    assert body["department"]["name"] == "IT"
    assert body["requester"]["full_name"] == "Mia"


async def test_priority_defaults_to_normal(hotel: Hotel) -> None:
    response = await create_request(hotel.mia, hotel.org_id, hotel.it)

    assert response.json()["priority"] == "normal"


async def test_create_records_created_event_in_timeline(hotel: Hotel) -> None:
    request_id = await create_request_id(hotel.mia, hotel.org_id, hotel.it)

    events = (await hotel.mia.get(requests_url(hotel, f"/{request_id}/events"))).json()

    assert [(e["event_type"], e["from_status"], e["to_status"]) for e in events] == [
        ("created", None, "open")
    ]
    assert events[0]["actor"]["full_name"] == "Mia"


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": "   "},
        {"title": "x" * 201},
        {"description": "x" * 5001},
        {"priority": "whenever"},
        {"department_id": "not-a-uuid"},
        {"status": "completed"},  # clients can't choose the initial status
    ],
)
async def test_create_rejects_invalid_input(hotel: Hotel, overrides: dict[str, str]) -> None:
    payload = {"title": "Broken lamp", "department_id": hotel.it, **overrides}

    response = await hotel.mia.post(requests_url(hotel), json=payload)

    assert response.status_code == 422


async def test_create_rejects_unknown_department(hotel: Hotel) -> None:
    response = await create_request(hotel.mia, hotel.org_id, str(uuid.uuid4()))

    assert response.status_code == 422
    assert response.json()["detail"] == "Department not found"


async def test_request_and_event_are_written_atomically(
    hotel: Hotel, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If writing the history event fails, the request must not exist either."""

    def failing_record_event(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated failure while recording the event")

    monkeypatch.setattr(request_service, "record_event", failing_record_event)

    with pytest.raises(RuntimeError, match="simulated failure"):
        await create_request(hotel.mia, hotel.org_id, hotel.it)

    assert await db_session.scalar(select(func.count()).select_from(Request)) == 0


# --- visibility ---------------------------------------------------------------


async def test_members_only_see_their_own_requests(hotel: Hotel) -> None:
    mias = await create_request_id(hotel.mia, hotel.org_id, hotel.it, title="Mia's issue")
    await create_request_id(hotel.max, hotel.org_id, hotel.it, title="Max's issue")

    mia_list = (await hotel.mia.get(requests_url(hotel))).json()["items"]
    agent_list = (await hotel.agent.get(requests_url(hotel))).json()["items"]

    assert [r["title"] for r in mia_list] == ["Mia's issue"]
    assert sorted(r["title"] for r in agent_list) == ["Max's issue", "Mia's issue"]
    assert (await hotel.mia.get(requests_url(hotel, f"/{mias}"))).status_code == 200


@pytest.mark.parametrize("suffix", ["", "/events"])
async def test_other_members_request_is_not_found(hotel: Hotel, suffix: str) -> None:
    mias = await create_request_id(hotel.mia, hotel.org_id, hotel.it)

    response = await hotel.max.get(requests_url(hotel, f"/{mias}{suffix}"))

    assert response.status_code == 404  # same as nonexistent: existence isn't revealed


async def test_staff_can_read_any_request_in_org(hotel: Hotel) -> None:
    mias = await create_request_id(hotel.mia, hotel.org_id, hotel.it)

    assert (await hotel.agent.get(requests_url(hotel, f"/{mias}"))).status_code == 200
    assert (await hotel.admin.get(requests_url(hotel, f"/{mias}/events"))).status_code == 200


# --- filters & pagination -----------------------------------------------------


async def test_filters_by_department_priority_and_status(
    hotel: Hotel, db_session: AsyncSession
) -> None:
    await create_request(hotel.mia, hotel.org_id, hotel.it, title="IT normal")
    await create_request(hotel.mia, hotel.org_id, hotel.it, title="IT urgent", priority="urgent")
    cancelled = await create_request_id(hotel.mia, hotel.org_id, hotel.housekeeping, title="HK")
    await db_session.execute(
        text("UPDATE requests SET status = 'cancelled', cancelled_at = now() WHERE id = :id"), {"id": cancelled}
    )
    await db_session.commit()

    async def titles(**params: str | list[str]) -> list[str]:
        response = await hotel.agent.get(requests_url(hotel), params=params)
        assert response.status_code == 200
        return sorted(r["title"] for r in response.json()["items"])

    assert await titles(department_id=hotel.it) == ["IT normal", "IT urgent"]
    assert await titles(priority="urgent") == ["IT urgent"]
    assert await titles(status="cancelled") == ["HK"]
    assert await titles(status=["open", "cancelled"]) == ["HK", "IT normal", "IT urgent"]


async def test_pagination_walks_newest_first_without_gaps_or_duplicates(hotel: Hotel) -> None:
    created = [
        await create_request_id(hotel.mia, hotel.org_id, hotel.it, title=f"Issue {n}")
        for n in range(5)
    ]

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params = {"limit": "2", **({"cursor": cursor} if cursor else {})}
        body = (await hotel.agent.get(requests_url(hotel), params=params)).json()
        seen += [r["id"] for r in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 3
    assert seen == list(reversed(created))


async def test_pagination_is_stable_when_new_requests_arrive(hotel: Hotel) -> None:
    """With OFFSET, a new row would shift page 2 and repeat an item. Keyset doesn't."""
    for n in range(4):
        await create_request_id(hotel.mia, hotel.org_id, hotel.it, title=f"Old {n}")
    first = (await hotel.agent.get(requests_url(hotel), params={"limit": "2"})).json()

    await create_request_id(hotel.mia, hotel.org_id, hotel.it, title="Arrived meanwhile")
    second = (
        await hotel.agent.get(
            requests_url(hotel), params={"limit": "2", "cursor": first["next_cursor"]}
        )
    ).json()

    assert [r["title"] for r in first["items"]] == ["Old 3", "Old 2"]
    assert [r["title"] for r in second["items"]] == ["Old 1", "Old 0"]


@pytest.mark.parametrize(
    "params", [{"cursor": "not-a-cursor"}, {"cursor": "W10"}, {"limit": "0"}, {"limit": "101"}]
)
async def test_list_rejects_invalid_paging_params(hotel: Hotel, params: dict[str, str]) -> None:
    response = await hotel.agent.get(requests_url(hotel), params=params)

    assert response.status_code == 422


# --- database guarantees ------------------------------------------------------


async def test_request_events_are_append_only(hotel: Hotel, db_session: AsyncSession) -> None:
    await create_request_id(hotel.mia, hotel.org_id, hotel.it)

    with pytest.raises(DBAPIError, match="append-only"):
        await db_session.execute(text("UPDATE request_events SET data = '{\"forged\": true}'"))
    await db_session.rollback()

    with pytest.raises(DBAPIError, match="append-only"):
        await db_session.execute(text("DELETE FROM request_events"))


@pytest.mark.parametrize(
    "update_sql",
    [
        "UPDATE requests SET status = 'assigned'",  # assigned without an assignee
        "UPDATE requests SET assignee_membership_id = requester_membership_id",  # open + assignee
    ],
)
async def test_status_and_assignee_must_agree(
    hotel: Hotel, db_session: AsyncSession, update_sql: str
) -> None:
    await create_request_id(hotel.mia, hotel.org_id, hotel.it)

    with pytest.raises(IntegrityError, match="ck_requests_status_matches_assignee"):
        await db_session.execute(text(update_sql))
