"""Organization and member use cases. Every function takes `organization_id` and
filters by it: there is deliberately no unscoped way to read tenant data."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.auth.service import USER_EMAIL_UNIQUE_CONSTRAINT, EmailAlreadyRegisteredError
from app.db import violated_constraint
from app.errors import ConflictError, NotFoundError
from app.organizations.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Organization,
)
from app.users.models import User

MemberRow = tuple[Membership, User]


class LastAdminError(ConflictError):
    def __init__(self) -> None:
        super().__init__("An organization must keep at least one active admin")


async def list_active_memberships(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Membership, Organization]]:
    """A user's own active memberships across organizations (for /me)."""
    result = await session.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user_id, Membership.status == MembershipStatus.ACTIVE)
        .order_by(Organization.name)
    )
    return [(membership, organization) for membership, organization in result]


def _members_query(organization_id: uuid.UUID):  # noqa: ANN202 - SQLAlchemy Select type is noisy
    return (
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == organization_id)
    )


async def list_members(session: AsyncSession, organization_id: uuid.UUID) -> list[MemberRow]:
    result = await session.execute(_members_query(organization_id).order_by(User.full_name))
    return [(membership, user) for membership, user in result]


async def get_member(
    session: AsyncSession, organization_id: uuid.UUID, membership_id: uuid.UUID
) -> MemberRow:
    row = (
        await session.execute(
            _members_query(organization_id)
            .where(Membership.id == membership_id)
            # Refresh objects already in this session's identity map (e.g. the caller's
            # own membership, loaded before a lock was taken) instead of reusing stale state.
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise NotFoundError("Member")
    membership, user = row
    return membership, user


async def add_member(
    session: AsyncSession,
    organization_id: uuid.UUID,
    *,
    email: str,
    full_name: str,
    password: str,
    role: MembershipRole,
) -> MemberRow:
    """Create a new user account directly inside this organization.

    Existing accounts are refused (409): an org admin must never attach someone
    else's account without consent, nor set its password. Joining additional
    organizations will come with invitations.
    """
    password_hash = await hash_password(password)
    user = User(email=email, full_name=full_name, password_hash=password_hash)
    try:
        session.add(user)
        await session.flush()
        membership = Membership(organization_id=organization_id, user_id=user.id, role=role)
        session.add(membership)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == USER_EMAIL_UNIQUE_CONSTRAINT:
            raise EmailAlreadyRegisteredError from exc
        raise
    return membership, user


async def _lock_organization(session: AsyncSession, organization_id: uuid.UUID) -> None:
    """Serialize admin-changing operations within one organization.

    Prevents write skew: two admins demoting each other concurrently would each
    see "one other admin remains" and both commit, leaving zero admins.
    """
    await session.execute(
        select(Organization.id).where(Organization.id == organization_id).with_for_update()
    )


async def update_member(
    session: AsyncSession,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    *,
    role: MembershipRole | None,
    status: MembershipStatus | None,
) -> MemberRow:
    await _lock_organization(session, organization_id)
    membership, user = await get_member(session, organization_id, membership_id)

    new_role = role or membership.role
    new_status = status or membership.status
    was_active_admin = (
        membership.role == MembershipRole.ADMIN and membership.status == MembershipStatus.ACTIVE
    )
    stays_active_admin = (
        new_role == MembershipRole.ADMIN and new_status == MembershipStatus.ACTIVE
    )
    if was_active_admin and not stays_active_admin:
        other_active_admins = await session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.organization_id == organization_id,
                Membership.role == MembershipRole.ADMIN,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.id != membership.id,
            )
        )
        if not other_active_admins:
            await session.rollback()
            raise LastAdminError

    membership.role = new_role
    membership.status = new_status
    await session.commit()
    return membership, user
