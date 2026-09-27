"""The database is the last line of defense: these rules hold even for writes
that bypass application code (scripts, bugs, manual SQL)."""

import uuid

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Organization,
)
from app.users.models import User


async def create_user(session: AsyncSession, email: str = "alice@example.com") -> User:
    user = User(email=email, full_name="Alice Example", password_hash="not-a-real-hash")
    session.add(user)
    await session.commit()
    return user


async def create_organization(session: AsyncSession, name: str = "Hotel A") -> Organization:
    organization = Organization(name=name)
    session.add(organization)
    await session.commit()
    return organization


async def test_user_email_must_be_unique(db_session: AsyncSession) -> None:
    await create_user(db_session, "alice@example.com")

    with pytest.raises(IntegrityError, match="uq_users_email"):
        await create_user(db_session, "alice@example.com")


async def test_user_email_must_be_stored_lowercase(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_users_email_lowercase"):
        await create_user(db_session, "Alice@Example.com")


async def test_membership_is_unique_per_organization_and_user(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    organization = await create_organization(db_session)
    db_session.add(
        Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.ADMIN)
    )
    await db_session.commit()

    db_session.add(
        Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.MEMBER)
    )
    with pytest.raises(IntegrityError, match="uq_memberships_organization_id_user_id"):
        await db_session.commit()


async def test_same_user_can_hold_different_roles_in_different_organizations(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    hotel_a = await create_organization(db_session, "Hotel A")
    hotel_b = await create_organization(db_session, "Hotel B")

    db_session.add_all(
        [
            Membership(organization_id=hotel_a.id, user_id=user.id, role=MembershipRole.ADMIN),
            Membership(organization_id=hotel_b.id, user_id=user.id, role=MembershipRole.MEMBER),
        ]
    )
    await db_session.commit()


async def test_membership_defaults_to_active(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    organization = await create_organization(db_session)
    membership = Membership(
        organization_id=organization.id, user_id=user.id, role=MembershipRole.AGENT
    )
    db_session.add(membership)
    await db_session.commit()

    assert membership.status is MembershipStatus.ACTIVE


async def test_membership_role_rejects_unknown_value_even_from_raw_sql(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    organization = await create_organization(db_session)

    with pytest.raises(IntegrityError, match="ck_memberships_membership_role"):
        await db_session.execute(
            text(
                "INSERT INTO memberships (id, organization_id, user_id, role) "
                "VALUES (:id, :org_id, :user_id, 'superadmin')"
            ),
            {"id": uuid.uuid4(), "org_id": organization.id, "user_id": user.id},
        )


async def test_membership_requires_existing_organization(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    db_session.add(
        Membership(organization_id=uuid.uuid4(), user_id=user.id, role=MembershipRole.MEMBER)
    )

    with pytest.raises(IntegrityError, match="fk_memberships_organization_id_organizations"):
        await db_session.commit()


async def test_user_with_memberships_cannot_be_deleted(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    organization = await create_organization(db_session)
    db_session.add(
        Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.MEMBER)
    )
    await db_session.commit()

    with pytest.raises(IntegrityError, match="fk_memberships_user_id_users"):
        await db_session.execute(delete(User).where(User.id == user.id))


async def test_updated_at_is_refreshed_on_update(db_session: AsyncSession) -> None:
    organization = await create_organization(db_session, "Old name")
    created_at = organization.created_at

    organization.name = "New name"
    await db_session.commit()

    # Readable without a lazy load (eager_defaults), and later than creation:
    # now() is the transaction start time, and this is a new transaction.
    assert organization.updated_at > created_at
