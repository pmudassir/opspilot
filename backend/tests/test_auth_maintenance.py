from collections.abc import Callable

from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.maintenance import LOGIN_ATTEMPT_RETENTION, delete_expired_auth_data
from app.auth.models import AuthSession, LoginAttempt
from tests.helpers import login, signup


async def test_cleanup_removes_only_expired_sessions_and_old_attempts(
    make_client: Callable[..., AsyncClient], db_session: AsyncSession
) -> None:
    await signup(make_client(), email="alice@example.com")  # active session
    await signup(make_client(), email="bob@example.com")
    await db_session.execute(
        text("UPDATE auth_sessions SET expires_at = now() - interval '1 minute' "
             "WHERE user_id = (SELECT id FROM users WHERE email = 'bob@example.com')")
    )
    await login(make_client(), email="alice@example.com", password="wrong-password-1")  # recent
    await login(make_client(), email="alice@example.com", password="wrong-password-2")
    await db_session.execute(
        text("UPDATE login_attempts SET created_at = now() - CAST(:age AS interval) "
             "WHERE id = (SELECT id FROM login_attempts ORDER BY created_at LIMIT 1)"),
        {"age": LOGIN_ATTEMPT_RETENTION + LOGIN_ATTEMPT_RETENTION / 10},
    )
    await db_session.commit()

    result = await delete_expired_auth_data(db_session)

    assert (result.expired_sessions, result.old_login_attempts) == (1, 1)
    assert await db_session.scalar(select(func.count()).select_from(AuthSession)) == 1
    assert await db_session.scalar(select(func.count()).select_from(LoginAttempt)) == 1
    # Idempotent: a second run has nothing left to delete.
    again = await delete_expired_auth_data(db_session)
    assert (again.expired_sessions, again.old_login_attempts) == (0, 0)
