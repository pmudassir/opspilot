"""Periodic cleanup of authentication data (run by scripts/cleanup_expired.py)."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthSession, LoginAttempt

# Throttling only needs 15 minutes; the rest is kept for security investigations.
LOGIN_ATTEMPT_RETENTION = timedelta(days=30)


@dataclass(frozen=True)
class CleanupResult:
    expired_sessions: int
    old_login_attempts: int


async def delete_expired_auth_data(session: AsyncSession) -> CleanupResult:
    sessions = await session.execute(delete(AuthSession).where(AuthSession.expires_at <= func.now()))
    attempts = await session.execute(
        delete(LoginAttempt).where(LoginAttempt.created_at < func.now() - LOGIN_ATTEMPT_RETENTION)
    )
    await session.commit()
    return CleanupResult(expired_sessions=sessions.rowcount, old_login_attempts=attempts.rowcount)
