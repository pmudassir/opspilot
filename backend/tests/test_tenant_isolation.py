"""Cross-tenant isolation: the security boundary of the whole product.

Every /orgs/{org_id}/... route is attacked three ways:
  1. another organization's org_id in the URL              → 404 (tenant context)
  2. own org_id, but another organization's object IDs     → 404 (scoped lookups / IDOR)
  3. no session at all                                      → 401
`test_every_org_route_is_covered` fails when a new org route is added without
being listed here, so the suite can't silently fall behind the API.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import (
    add_member_id,
    create_department_id,
    logged_in,
    org_url,
    signup_org,
)

ORG_ROUTE_PREFIX = "/api/v1/orgs/{org_id}"


@dataclass(frozen=True)
class RouteCase:
    method: str
    path: str  # template relative to ORG_ROUTE_PREFIX
    json: dict[str, Any] | None = None

    @property
    def id(self) -> str:
        return f"{self.method} {self.path or '/'}"

    @property
    def has_object_ids(self) -> bool:
        return "{department_id}" in self.path or "{membership_id}" in self.path


ORG_ROUTES = [
    RouteCase("GET", ""),
    RouteCase("GET", "/members"),
    RouteCase(
        "POST",
        "/members",
        {"email": "intruder@example.com", "full_name": "X", "password": "p" * 12, "role": "admin"},
    ),
    RouteCase("PATCH", "/members/{membership_id}", {"role": "member"}),
    RouteCase("GET", "/departments"),
    RouteCase("POST", "/departments", {"name": "Hijacked"}),
    RouteCase("GET", "/departments/{department_id}/members"),
    RouteCase("PUT", "/departments/{department_id}/members/{membership_id}"),
    RouteCase("DELETE", "/departments/{department_id}/members/{membership_id}"),
]


@dataclass(frozen=True)
class World:
    """Two organizations, each with an admin, an agent, and an IT department."""

    alice: AsyncClient  # admin of Hotel A
    bob: AsyncClient  # admin of Hotel B
    org_a: str
    org_b: str
    carol_membership_a: str  # agent in A, member of A's IT
    dave_membership_b: str  # agent in B
    it_department_a: str
    it_department_b: str


@pytest.fixture
async def world(make_client: Callable[[], AsyncClient]) -> World:
    alice, bob = make_client(), make_client()
    org_a = await signup_org(alice, email="alice@a.example", organization_name="Hotel A")
    org_b = await signup_org(bob, email="bob@b.example", organization_name="Hotel B")
    carol = await add_member_id(alice, org_a, email="carol@a.example")
    dave = await add_member_id(bob, org_b, email="dave@b.example")
    it_a = await create_department_id(alice, org_a, "IT")
    it_b = await create_department_id(bob, org_b, "IT")
    assert (await alice.put(org_url(org_a, f"/departments/{it_a}/members/{carol}"))).status_code == 204
    return World(alice, bob, org_a, org_b, carol, dave, it_a, it_b)


async def send(
    client: AsyncClient,
    route: RouteCase,
    *,
    org_id: str,
    department_id: str,
    membership_id: str,
) -> int:
    url = (ORG_ROUTE_PREFIX + route.path).format(
        org_id=org_id, department_id=department_id, membership_id=membership_id
    )
    response = await client.request(route.method, url, json=route.json)
    return response.status_code


def test_every_org_route_is_covered(app: FastAPI) -> None:
    registered = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(ORG_ROUTE_PREFIX)
        for method in operations
    }
    covered = {(route.method, ORG_ROUTE_PREFIX + route.path) for route in ORG_ROUTES}

    assert registered == covered, "Add new org routes to ORG_ROUTES in this file"


@pytest.mark.parametrize("route", ORG_ROUTES, ids=lambda r: r.id)
async def test_foreign_org_id_in_url_is_not_found(world: World, route: RouteCase) -> None:
    status = await send(
        world.bob,
        route,
        org_id=world.org_a,
        department_id=world.it_department_a,
        membership_id=world.carol_membership_a,
    )

    assert status == 404


@pytest.mark.parametrize(
    "route", [r for r in ORG_ROUTES if r.has_object_ids], ids=lambda r: r.id
)
async def test_foreign_object_ids_under_own_org_are_not_found(
    world: World, route: RouteCase
) -> None:
    status = await send(
        world.bob,
        route,
        org_id=world.org_b,
        department_id=world.it_department_a,
        membership_id=world.carol_membership_a,
    )

    assert status == 404


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
async def test_foreign_department_with_own_member_is_not_found(world: World, method: str) -> None:
    """Each ID must be checked on its own: here only the department is foreign."""
    url = org_url(world.org_b, f"/departments/{world.it_department_a}/members/{world.dave_membership_b}")

    assert (await world.bob.request(method, url)).status_code == 404


async def test_cannot_add_foreign_member_to_own_department(world: World) -> None:
    url = org_url(world.org_b, f"/departments/{world.it_department_b}/members/{world.carol_membership_a}")

    assert (await world.bob.put(url)).status_code == 404


@pytest.mark.parametrize("route", ORG_ROUTES, ids=lambda r: r.id)
async def test_unauthenticated_requests_are_rejected(
    world: World, make_client: Callable[[], AsyncClient], route: RouteCase
) -> None:
    status = await send(
        make_client(),
        route,
        org_id=world.org_a,
        department_id=world.it_department_a,
        membership_id=world.carol_membership_a,
    )

    assert status == 401


async def test_attacks_leave_victim_organization_unchanged(world: World) -> None:
    for route in ORG_ROUTES:
        for org_id in (world.org_a, world.org_b):
            await send(
                world.bob,
                route,
                org_id=org_id,
                department_id=world.it_department_a,
                membership_id=world.carol_membership_a,
            )

    members = (await world.alice.get(org_url(world.org_a, "/members"))).json()
    departments = (await world.alice.get(org_url(world.org_a, "/departments"))).json()
    it_members = (
        await world.alice.get(org_url(world.org_a, f"/departments/{world.it_department_a}/members"))
    ).json()
    assert sorted((m["email"], m["role"], m["status"]) for m in members) == [
        ("alice@a.example", "admin", "active"),
        ("carol@a.example", "agent", "active"),
    ]
    assert [d["name"] for d in departments] == ["IT"]
    assert [m["email"] for m in it_members] == ["carol@a.example"]


async def test_deactivated_member_loses_access_immediately(
    world: World, make_client: Callable[[], AsyncClient]
) -> None:
    carol = await logged_in(make_client(), "carol@a.example")
    assert (await carol.get(org_url(world.org_a))).status_code == 200

    response = await world.alice.patch(
        org_url(world.org_a, f"/members/{world.carol_membership_a}"), json={"status": "deactivated"}
    )
    assert response.status_code == 200

    # Same session cookie, next request: membership status is checked every time.
    assert (await carol.get(org_url(world.org_a))).status_code == 404


async def test_database_rejects_cross_tenant_department_membership(
    world: World, db_session: AsyncSession
) -> None:
    """Even if application code forgot the checks, the composite FKs would not."""
    insert = text(
        "INSERT INTO department_members (organization_id, department_id, membership_id) "
        "VALUES (:org, :department, :membership)"
    )

    with pytest.raises(IntegrityError, match="fk_department_members_membership"):
        await db_session.execute(
            insert,
            {"org": world.org_a, "department": world.it_department_a, "membership": world.dave_membership_b},
        )
    await db_session.rollback()

    with pytest.raises(IntegrityError, match="fk_department_members_department"):
        await db_session.execute(
            insert,
            {"org": world.org_b, "department": world.it_department_a, "membership": world.dave_membership_b},
        )


async def test_random_org_id_is_not_found(world: World) -> None:
    assert (await world.alice.get(org_url(str(uuid.uuid4())))).status_code == 404
