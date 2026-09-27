from collections.abc import Callable

import pytest
from httpx import AsyncClient

from tests.helpers import (
    add_member_id,
    create_department,
    create_department_id,
    org_url,
    signup_org,
)


@pytest.fixture
async def admin_and_org(make_client: Callable[[], AsyncClient]) -> tuple[AsyncClient, str]:
    admin = make_client()
    org_id = await signup_org(admin, email="alice@a.example", organization_name="Hotel A")
    return admin, org_id


async def test_create_and_list_departments_sorted_by_name(
    admin_and_org: tuple[AsyncClient, str],
) -> None:
    admin, org_id = admin_and_org
    for name in ["Maintenance", "Housekeeping", "  IT  "]:
        assert (await create_department(admin, org_id, name)).status_code == 201

    names = [d["name"] for d in (await admin.get(org_url(org_id, "/departments"))).json()]

    assert names == ["Housekeeping", "IT", "Maintenance"]


async def test_department_names_are_unique_per_org_case_insensitively(
    admin_and_org: tuple[AsyncClient, str],
) -> None:
    admin, org_id = admin_and_org
    await create_department_id(admin, org_id, "IT")

    assert (await create_department(admin, org_id, "it")).status_code == 409


async def test_same_department_name_is_allowed_in_different_orgs(
    admin_and_org: tuple[AsyncClient, str], make_client: Callable[[], AsyncClient]
) -> None:
    admin_a, org_a = admin_and_org
    admin_b = make_client()
    org_b = await signup_org(admin_b, email="bob@b.example", organization_name="Hotel B")

    assert (await create_department(admin_a, org_a, "IT")).status_code == 201
    assert (await create_department(admin_b, org_b, "IT")).status_code == 201


async def test_blank_department_name_is_rejected(admin_and_org: tuple[AsyncClient, str]) -> None:
    admin, org_id = admin_and_org

    assert (await create_department(admin, org_id, "   ")).status_code == 422


async def test_adding_department_member_is_idempotent(
    admin_and_org: tuple[AsyncClient, str],
) -> None:
    admin, org_id = admin_and_org
    department_id = await create_department_id(admin, org_id, "IT")
    carol_id = await add_member_id(admin, org_id, email="carol@a.example")
    url = org_url(org_id, f"/departments/{department_id}/members/{carol_id}")

    assert (await admin.put(url)).status_code == 204
    assert (await admin.put(url)).status_code == 204  # retry: same result, no error

    members = (await admin.get(org_url(org_id, f"/departments/{department_id}/members"))).json()
    assert [m["email"] for m in members] == ["carol@a.example"]


async def test_removing_department_member_is_idempotent(
    admin_and_org: tuple[AsyncClient, str],
) -> None:
    admin, org_id = admin_and_org
    department_id = await create_department_id(admin, org_id, "IT")
    carol_id = await add_member_id(admin, org_id, email="carol@a.example")
    url = org_url(org_id, f"/departments/{department_id}/members/{carol_id}")
    await admin.put(url)

    assert (await admin.delete(url)).status_code == 204
    assert (await admin.delete(url)).status_code == 204

    members = (await admin.get(org_url(org_id, f"/departments/{department_id}/members"))).json()
    assert members == []


async def test_deactivated_member_cannot_join_department(
    admin_and_org: tuple[AsyncClient, str],
) -> None:
    admin, org_id = admin_and_org
    department_id = await create_department_id(admin, org_id, "IT")
    carol_id = await add_member_id(admin, org_id, email="carol@a.example")
    await admin.patch(org_url(org_id, f"/members/{carol_id}"), json={"status": "deactivated"})

    response = await admin.put(org_url(org_id, f"/departments/{department_id}/members/{carol_id}"))

    assert response.status_code == 409
