import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.models import Membership, MembershipStatus, Organization


async def list_active_memberships(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Membership, Organization]]:
    result = await session.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user_id, Membership.status == MembershipStatus.ACTIVE)
        .order_by(Organization.name)
    )
    return [(membership, organization) for membership, organization in result]
