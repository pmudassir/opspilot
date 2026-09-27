"""Authentication use cases. Services own the transaction: they commit on success;
anything uncommitted is rolled back when the request's DB session closes."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthSession
from app.auth.passwords import hash_password, verify_password
from app.db import violated_constraint
from app.organizations.models import Membership, MembershipRole, Organization
from app.users.models import User

SESSION_TOKEN_BYTES = 32
USER_EMAIL_UNIQUE_CONSTRAINT = "uq_users_email"


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


@dataclass(frozen=True)
class IssuedSession:
    token: str
    expires_at: datetime


def hash_session_token(token: str) -> bytes:
    # A fast hash is fine here: the token is 256 random bits, so there is nothing to brute-force.
    return hashlib.sha256(token.encode()).digest()


def _add_auth_session(session: AsyncSession, user_id: uuid.UUID, ttl: timedelta) -> IssuedSession:
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    expires_at = datetime.now(UTC) + ttl
    session.add(
        AuthSession(user_id=user_id, token_hash=hash_session_token(token), expires_at=expires_at)
    )
    return IssuedSession(token=token, expires_at=expires_at)


async def register(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    organization_name: str,
    session_ttl: timedelta,
) -> tuple[User, IssuedSession]:
    """Create user + organization + admin membership + login session atomically.

    No "does this email exist?" pre-check: two concurrent signups would both pass it.
    The UNIQUE constraint is the single source of truth.
    """
    password_hash = await hash_password(password)
    user = User(email=email, full_name=full_name, password_hash=password_hash)
    organization = Organization(name=organization_name)
    try:
        session.add_all([user, organization])
        await session.flush()  # assigns ids; raises here on a duplicate email
        session.add(
            Membership(
                organization_id=organization.id, user_id=user.id, role=MembershipRole.ADMIN
            )
        )
        issued = _add_auth_session(session, user.id, session_ttl)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == USER_EMAIL_UNIQUE_CONSTRAINT:
            raise EmailAlreadyRegisteredError from exc
        raise
    return user, issued


async def login(
    session: AsyncSession, *, email: str, password: str, session_ttl: timedelta
) -> tuple[User, IssuedSession]:
    user = await session.scalar(select(User).where(User.email == email))
    password_hash = user.password_hash if user is not None else None
    if user is None or not await verify_password(password_hash, password):
        raise InvalidCredentialsError
    issued = _add_auth_session(session, user.id, session_ttl)
    await session.commit()
    return user, issued


async def logout(session: AsyncSession, token: str) -> None:
    """Revoke the session server-side. Idempotent: unknown tokens are a no-op."""
    await session.execute(
        delete(AuthSession).where(AuthSession.token_hash == hash_session_token(token))
    )
    await session.commit()


async def get_user_by_session_token(session: AsyncSession, token: str) -> User | None:
    return await session.scalar(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == hash_session_token(token),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
