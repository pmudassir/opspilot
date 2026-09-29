"""Create a realistic demo organization for local development and demos.

Usage (from backend/): uv run python -m scripts.seed_demo
- Goes through the real service functions, so history events and rules match real use.
- Safe to re-run: if the demo admin exists, it only prints the logins.
- Refuses to run with ENVIRONMENT=production.
"""

import asyncio
import sys
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthSession
from app.auth.service import register
from app.comments.service import add_comment
from app.config import get_settings
from app.db import SessionFactory, engine
from app.departments.service import add_department_member, create_department
from app.organizations.models import Membership, MembershipRole
from app.organizations.service import add_member
from app.requests import lifecycle
from app.requests.models import RequestPriority
from app.requests.service import create_request, viewer_for
from app.users.models import User

DOMAIN = "harborview.example"
PASSWORD = "demo-password-123"
ORGANIZATION = "Harbor View Hotel"

ADMIN = ("priya", "Priya Raman")
STAFF: list[tuple[str, str, MembershipRole, list[str]]] = [
    ("diego", "Diego Alvarez", MembershipRole.MANAGER, ["IT", "Maintenance"]),
    ("sam", "Sam Okafor", MembershipRole.AGENT, ["IT", "Maintenance"]),
    ("lena", "Lena Fischer", MembershipRole.AGENT, ["Housekeeping"]),
    ("mia", "Mia Wong", MembershipRole.MEMBER, []),
    ("tom", "Tom Hughes", MembershipRole.MEMBER, []),
]
DEPARTMENTS = ["Front Desk", "Housekeeping", "IT", "Maintenance"]


def email(handle: str) -> str:
    return f"{handle}@{DOMAIN}"


@dataclass(frozen=True)
class SeedResult:
    created: bool
    logins: list[tuple[str, str]]  # (email, role)


def _logins() -> list[tuple[str, str]]:
    return [(email(ADMIN[0]), "admin")] + [(email(handle), role.value) for handle, _, role, _ in STAFF]


async def seed(session: AsyncSession) -> SeedResult:
    if await session.scalar(select(User.id).where(User.email == email(ADMIN[0]))):
        return SeedResult(created=False, logins=_logins())

    admin_user, _ = await register(
        session,
        email=email(ADMIN[0]),
        password=PASSWORD,
        full_name=ADMIN[1],
        organization_name=ORGANIZATION,
        session_ttl=timedelta(hours=1),
    )
    # register() also logs the admin in; the seed shouldn't leave a live session behind.
    await session.execute(delete(AuthSession).where(AuthSession.user_id == admin_user.id))
    await session.commit()
    admin = await session.scalar(select(Membership).where(Membership.user_id == admin_user.id))
    assert admin is not None
    org = admin.organization_id

    departments = {name: (await create_department(session, org, name)).id for name in DEPARTMENTS}
    people: dict[str, Membership] = {"priya": admin}
    for handle, full_name, role, department_names in STAFF:
        membership, _ = await add_member(
            session, org, email=email(handle), full_name=full_name, password=PASSWORD, role=role
        )
        people[handle] = membership
        for name in department_names:
            await add_department_member(session, org, departments[name], membership.id)

    async def report(who: str, department: str, title: str, description: str, priority: RequestPriority) -> str:
        row = await create_request(
            session,
            org,
            requester_membership_id=people[who].id,
            department_id=departments[department],
            title=title,
            description=description,
            priority=priority,
        )
        return str(row.request.id)

    async def comment(who: str, request_id: str, body: str) -> None:
        await add_comment(
            session, org, request_id, author=people[who], viewer=viewer_for(people[who]), body=body
        )

    P = RequestPriority
    # Open, unassigned
    await report("mia", "IT", "Wi-Fi keeps dropping in meeting room 2", "Client meeting at 3pm; drops every few minutes.", P.URGENT)
    await report("tom", "Housekeeping", "Room 412 needs extra towels", "Guest asked twice at the front desk.", P.NORMAL)
    await report("mia", "Maintenance", "Flickering light in the lobby corridor", "", P.LOW)
    await report("tom", "Front Desk", "Key card encoder not responding", "Can't issue new keys; using the backup encoder.", P.HIGH)

    # Assigned
    printer = await report("tom", "IT", "Printer at front desk jams on every job", "Tried a new paper tray.", P.HIGH)
    await lifecycle.assign(session, org, printer, people["diego"], people["sam"].id)

    # In progress, with a conversation
    ac = await report("mia", "Maintenance", "AC unit in room 305 is leaking", "Water on the carpet under the unit.", P.HIGH)
    await lifecycle.claim(session, org, ac, people["sam"])
    await lifecycle.start(session, org, ac, people["sam"])
    await comment("sam", ac, "Condensate line is blocked. Clearing it now.")
    await comment("mia", ac, "Thanks! The guest checks in at 6pm.")

    towels = await report("tom", "Housekeeping", "Spill in the east stairwell", "Coffee, second-floor landing.", P.HIGH)
    await lifecycle.claim(session, org, towels, people["lena"])
    await lifecycle.start(session, org, towels, people["lena"])

    # Completed
    projector = await report("mia", "IT", "Projector remote missing in ballroom", "", P.NORMAL)
    await lifecycle.claim(session, org, projector, people["sam"])
    await lifecycle.start(session, org, projector, people["sam"])
    await comment("sam", projector, "Found it in the AV cabinet; added a spare.")
    await lifecycle.complete(session, org, projector, people["sam"])

    # Cancelled
    duplicate = await report("tom", "IT", "Wi-Fi down in meeting room 2", "", P.HIGH)
    await comment("diego", duplicate, "Duplicate of Mia's report; tracking it there.")
    await lifecycle.cancel(session, org, duplicate, people["diego"])

    return SeedResult(created=True, logins=_logins())


async def main() -> None:
    if get_settings().environment == "production":
        sys.exit("Refusing to seed demo data with ENVIRONMENT=production")
    try:
        async with SessionFactory() as session:
            result = await seed(session)
    finally:
        await engine.dispose()
    print("Demo organization created." if result.created else "Demo data already present.")
    print(f"Log in with any of these (password: {PASSWORD}):")
    for login_email, role in result.logins:
        print(f"  {login_email:<32} {role}")


if __name__ == "__main__":
    asyncio.run(main())
