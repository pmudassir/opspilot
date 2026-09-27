import asyncio
import contextlib
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.models import Membership, MembershipRole, MembershipStatus
from tests.helpers import (
    add_member,
    add_member_id,
    create_department_id,
    logged_in,
    login,
    org_url,
    signup,
    signup_org,
)


@pytest.fixture
async def admin_and_org(make_client: Callable[[], AsyncClient]) -> tuple[AsyncClient, str]:
    admin = make_client()
    org_id = await signup_org(admin, email="alice@a.example", organization_name="Hotel A")
    return admin, org_id


async def test_admin_adds_member_who_can_then_log_in(
    admin_and_org: tuple[AsyncClient, str], make_client: Callable[[], AsyncClient]
) -> None:
    admin, org_id = admin_and_org

    response = await add_member(admin, org_id, email="Carol@A.example", role="agent")

    assert response.status_code == 201
    assert response.json()["email"] == "carol@a.example"
    assert response.json()["role"] == "agent"
    me = (await login(make_client(), email="carol@a.example")).json()
    assert [(m["organization_id"], m["role"]) for m in me["memberships"]] == [(org_id, "agent")]


async def test_admin_cannot_attach_or_take_over_an_existing_account(
    admin_and_org: tuple[AsyncClient, str], make_client: Callable[[], AsyncClient]
) -> None:
    admin, org_id = admin_and_org
    await signup(make_client(), email="bob@b.example", password="bobs-own-password", organization_name="Hotel B")

    response = await add_member(admin, org_id, email="bob@b.example", password="attacker-chosen-pw")

    assert response.status_code == 409
    assert (await login(make_client(), email="bob@b.example", password="bobs-own-password")).status_code == 200
    assert (await login(make_client(), email="bob@b.example", password="attacker-chosen-pw")).status_code == 401


# Expected status per (role, action). Admin is covered by the positive tests.
PERMISSION_MATRIX = {
    #                         member agent manager
    "GET org":               (200,   200,  200),
    "GET members":           (403,   200,  200),
    "POST members":          (403,   403,  403),
    "PATCH member":          (403,   403,  403),
    "GET departments":       (200,   200,  200),
    "POST departments":      (403,   403,  403),
    "GET dept members":      (403,   200,  200),
    "PUT dept member":       (403,   403,  403),
    "DELETE dept member":    (403,   403,  403),
}  # fmt: skip


@pytest.mark.parametrize(("role_index", "role"), list(enumerate(["member", "agent", "manager"])))
async def test_role_permissions(
    admin_and_org: tuple[AsyncClient, str],
    make_client: Callable[[], AsyncClient],
    role_index: int,
    role: str,
) -> None:
    admin, org_id = admin_and_org
    membership_id = await add_member_id(admin, org_id, email="user@a.example", role=role)
    department_id = await create_department_id(admin, org_id, "IT")
    user = await logged_in(make_client(), "user@a.example")
    dept_member = f"/departments/{department_id}/members/{membership_id}"
    new_member = {"email": "x@a.example", "full_name": "X", "password": "p" * 12, "role": "admin"}

    actual = {
        "GET org": (await user.get(org_url(org_id))).status_code,
        "GET members": (await user.get(org_url(org_id, "/members"))).status_code,
        "POST members": (await user.post(org_url(org_id, "/members"), json=new_member)).status_code,
        "PATCH member": (
            await user.patch(org_url(org_id, f"/members/{membership_id}"), json={"role": "admin"})
        ).status_code,
        "GET departments": (await user.get(org_url(org_id, "/departments"))).status_code,
        "POST departments": (
            await user.post(org_url(org_id, "/departments"), json={"name": "Ops"})
        ).status_code,
        "GET dept members": (
            await user.get(org_url(org_id, f"/departments/{department_id}/members"))
        ).status_code,
        "PUT dept member": (await user.put(org_url(org_id, dept_member))).status_code,
        "DELETE dept member": (await user.delete(org_url(org_id, dept_member))).status_code,
    }

    expected = {action: statuses[role_index] for action, statuses in PERMISSION_MATRIX.items()}
    assert actual == expected


async def test_admin_changes_member_role(admin_and_org: tuple[AsyncClient, str]) -> None:
    admin, org_id = admin_and_org
    membership_id = await add_member_id(admin, org_id, email="carol@a.example", role="agent")

    response = await admin.patch(org_url(org_id, f"/members/{membership_id}"), json={"role": "manager"})

    assert response.status_code == 200
    assert response.json()["role"] == "manager"


@pytest.mark.parametrize("change", [{"role": "agent"}, {"status": "deactivated"}])
async def test_last_active_admin_cannot_be_removed(
    admin_and_org: tuple[AsyncClient, str], change: dict[str, str]
) -> None:
    admin, org_id = admin_and_org
    own_membership_id = (await admin.get(org_url(org_id, "/members"))).json()[0]["membership_id"]

    response = await admin.patch(org_url(org_id, f"/members/{own_membership_id}"), json=change)

    assert response.status_code == 409


async def test_admin_can_step_down_when_another_admin_exists(
    admin_and_org: tuple[AsyncClient, str],
) -> None:
    admin, org_id = admin_and_org
    await add_member_id(admin, org_id, email="carol@a.example", role="admin")
    members = (await admin.get(org_url(org_id, "/members"))).json()
    alice_id = next(m["membership_id"] for m in members if m["email"] == "alice@a.example")

    response = await admin.patch(org_url(org_id, f"/members/{alice_id}"), json={"role": "agent"})

    assert response.status_code == 200


RENDEZVOUS_TIMEOUT_SECONDS = 0.5


async def test_concurrent_mutual_demotion_keeps_one_admin(
    admin_and_org: tuple[AsyncClient, str],
    make_client: Callable[[], AsyncClient],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write skew: two admins demote each other at the same moment.

    To force the dangerous interleaving deterministically (instead of hoping the
    scheduler produces it), every commit first waits until both transactions have
    reached commit — i.e. both have already checked "another admin remains".
    - Without the org row lock: both pass the check, both commit → zero admins.
    - With it: the second transaction is blocked on the lock and never reaches commit;
      the first times out of the rendezvous, commits, and the second then sees the
      committed demotion and is refused (409).
    """
    alice, org_id = admin_and_org
    carol_id = await add_member_id(alice, org_id, email="carol@a.example", role="admin")
    carol = await logged_in(make_client(), "carol@a.example")
    members = (await alice.get(org_url(org_id, "/members"))).json()
    alice_id = next(m["membership_id"] for m in members if m["email"] == "alice@a.example")

    original_commit = AsyncSession.commit
    arrived_at_commit = 0
    both_arrived = asyncio.Event()

    async def commit_after_rendezvous(self: AsyncSession) -> None:
        nonlocal arrived_at_commit
        arrived_at_commit += 1
        if arrived_at_commit >= 2:
            both_arrived.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(both_arrived.wait(), RENDEZVOUS_TIMEOUT_SECONDS)
        await original_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", commit_after_rendezvous)

    responses = await asyncio.gather(
        alice.patch(org_url(org_id, f"/members/{carol_id}"), json={"role": "agent"}),
        carol.patch(org_url(org_id, f"/members/{alice_id}"), json={"role": "agent"}),
    )

    monkeypatch.undo()
    assert sorted(r.status_code for r in responses) == [200, 409]
    active_admins = await db_session.scalar(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.role == MembershipRole.ADMIN, Membership.status == MembershipStatus.ACTIVE
        )
    )
    assert active_admins == 1


async def test_update_requires_at_least_one_field(admin_and_org: tuple[AsyncClient, str]) -> None:
    admin, org_id = admin_and_org
    membership_id = await add_member_id(admin, org_id, email="carol@a.example")

    response = await admin.patch(org_url(org_id, f"/members/{membership_id}"), json={})

    assert response.status_code == 422
