from collections.abc import Callable

import pytest
from httpx import AsyncClient

from tests.helpers import (
    add_member_id,
    create_department_id,
    create_request_id,
    logged_in,
    org_url,
    signup_org,
)


@pytest.fixture
async def setup(make_client: Callable[[], AsyncClient]) -> dict[str, AsyncClient | str]:
    admin = make_client()
    org_id = await signup_org(admin, email="alice@a.example", organization_name="Hotel A")
    for name, role in [("agent", "agent"), ("mia", "member"), ("max", "member")]:
        await add_member_id(admin, org_id, email=f"{name}@a.example", role=role)
    it = await create_department_id(admin, org_id, "IT")
    mia = await logged_in(make_client(), "mia@a.example")
    request_id = await create_request_id(mia, org_id, it)
    return {
        "org_id": org_id,
        "request_id": request_id,
        "url": org_url(org_id, f"/requests/{request_id}/comments"),
        "mia": mia,
        "max": await logged_in(make_client(), "max@a.example"),
        "agent": await logged_in(make_client(), "agent@a.example"),
    }


async def test_requester_and_staff_comment_and_read_in_order(setup: dict) -> None:
    first = await setup["mia"].post(setup["url"], json={"body": "  It dropped again  "})
    second = await setup["agent"].post(setup["url"], json={"body": "On my way"})

    assert first.status_code == second.status_code == 201
    comments = (await setup["mia"].get(setup["url"])).json()
    assert [(c["author"]["full_name"], c["body"]) for c in comments] == [
        ("Mia", "It dropped again"),
        ("Agent", "On my way"),
    ]


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_members_cannot_comment_on_or_read_others_requests(
    setup: dict, method: str
) -> None:
    response = await setup["max"].request(method, setup["url"], json={"body": "hi"} if method == "POST" else None)

    assert response.status_code == 404


@pytest.mark.parametrize("body", ["   ", "x" * 5001])
async def test_comment_body_is_validated(setup: dict, body: str) -> None:
    assert (await setup["mia"].post(setup["url"], json={"body": body})).status_code == 422


async def test_can_comment_on_a_cancelled_request(setup: dict) -> None:
    cancel_url = org_url(setup["org_id"], f"/requests/{setup['request_id']}/cancel")
    assert (await setup["mia"].post(cancel_url)).status_code == 200

    assert (await setup["mia"].post(setup["url"], json={"body": "Never mind"})).status_code == 201
