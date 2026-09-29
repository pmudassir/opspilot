from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthSession
from app.requests.models import Request, RequestStatus
from scripts.seed_demo import seed


async def test_seed_creates_a_demo_with_every_status_and_is_rerunnable(db_session: AsyncSession) -> None:
    first = await seed(db_session)
    second = await seed(db_session)

    assert first.created and not second.created
    assert {role for _, role in first.logins} == {"admin", "manager", "agent", "member"}
    statuses = set((await db_session.scalars(select(Request.status))).all())
    assert statuses == set(RequestStatus)
    assert await db_session.scalar(select(func.count()).select_from(Request)) == 9
    assert await db_session.scalar(select(func.count()).select_from(AuthSession)) == 0
