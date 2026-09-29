"""Login throttling, backed by Postgres (shared by all workers, survives restarts).

Rules (failed attempts within WINDOW):
- per (email, ip): 5   → a guesser at one address gets 5 tries per account
- per ip:          30  → one address trying many accounts (credential stuffing)
- per email:       20  → bounds guessing on one account even if IPs are rotated or
                         spoofed; trade-off: an attacker can lock an account for ≤ WINDOW
Checked *before* the password hash, so a throttled request costs no argon2 work.
Unknown emails are throttled exactly like real ones (the 429 reveals nothing).
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import LoginAttempt
from app.errors import DomainError

WINDOW = timedelta(minutes=15)


@dataclass(frozen=True)
class Rule:
    name: str
    limit: int


PER_EMAIL_AND_IP = Rule("email_and_ip", 5)
PER_IP = Rule("ip", 30)
PER_EMAIL = Rule("email", 20)


class TooManyLoginAttemptsError(DomainError):
    status_code = 429

    def __init__(self, retry_after_seconds: int) -> None:
        minutes = max(1, math.ceil(retry_after_seconds / 60))
        super().__init__(
            f"Too many failed sign-in attempts. Try again in {minutes} minute{'s' if minutes > 1 else ''}."
        )
        self.headers = {"Retry-After": str(retry_after_seconds)}


def _recent_failures(condition: ColumnElement[bool]) -> ColumnElement[bool]:
    return and_(
        condition,
        LoginAttempt.succeeded.is_(False),
        LoginAttempt.created_at > func.now() - WINDOW,
    )


async def _oldest_counted(
    session: AsyncSession, rule: Rule, condition: ColumnElement[bool]
) -> datetime | None:
    """If `rule` is exceeded, the time its oldest counted failure was recorded."""
    row = (
        await session.execute(
            select(func.count(), func.min(LoginAttempt.created_at)).where(
                _recent_failures(condition)
            )
        )
    ).one()
    count, oldest = row
    return oldest if count >= rule.limit else None


async def ensure_login_allowed(session: AsyncSession, *, email: str, ip: str) -> None:
    rules = [
        (PER_EMAIL_AND_IP, and_(LoginAttempt.email == email, LoginAttempt.ip == ip)),
        (PER_IP, LoginAttempt.ip == ip),
        (PER_EMAIL, LoginAttempt.email == email),
    ]
    blocked_since = [
        oldest
        for rule, condition in rules
        if (oldest := await _oldest_counted(session, rule, condition)) is not None
    ]
    if not blocked_since:
        return
    now = await session.scalar(select(func.now()))
    assert now is not None
    # Allowed again once the oldest counted failure leaves the window (per exceeded rule;
    # the caller must wait for the *latest* of those).
    retry_after = max((oldest + WINDOW - now).total_seconds() for oldest in blocked_since)
    raise TooManyLoginAttemptsError(max(1, math.ceil(retry_after)))


def record_login_attempt(session: AsyncSession, *, email: str, ip: str, succeeded: bool) -> None:
    """Added to the caller's transaction. Throttled attempts are not recorded."""
    session.add(LoginAttempt(email=email, ip=ip, succeeded=succeeded))
