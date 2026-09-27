"""Tenant context: the only way an org route learns which organization it acts on.

Order of checks for every /orgs/{org_id}/... request:
  1. authenticated user (session cookie)            → 401
  2. active membership in {org_id}                  → 404 (don't reveal the org exists)
  3. role has the required permission               → 403
  4. object lookups filter by organization_id       → 404 (in services)
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from app.auth.dependencies import CurrentUserDep
from app.db import SessionDep
from app.organizations.models import Membership, MembershipStatus, Organization
from app.permissions import Permission, has_permission
from app.users.models import User


@dataclass(frozen=True)
class TenantContext:
    user: User
    membership: Membership
    organization: Organization

    @property
    def organization_id(self) -> uuid.UUID:
        return self.organization.id


async def get_tenant_context(
    org_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> TenantContext:
    row = (
        await session.execute(
            select(Membership, Organization)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(
                Membership.organization_id == org_id,
                Membership.user_id == user.id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    membership, organization = row
    return TenantContext(user=user, membership=membership, organization=organization)


TenantContextDep = Annotated[TenantContext, Depends(get_tenant_context)]


def require_permission(permission: Permission) -> Callable[..., Awaitable[TenantContext]]:
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not has_permission(context.membership.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to perform this action",
            )
        return context

    return dependency


def authorized(permission: Permission) -> type[TenantContext]:
    """`context: authorized(Permission.X)` — tenant context + permission check."""
    return Annotated[TenantContext, Depends(require_permission(permission))]  # type: ignore[return-value]
