"""Department use cases. Every function is scoped by `organization_id`."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import violated_constraint
from app.departments.models import (
    DEPARTMENT_NAME_UNIQUE_INDEX,
    Department,
    DepartmentMember,
)
from app.errors import ConflictError, NotFoundError
from app.organizations.models import Membership, MembershipStatus
from app.organizations.service import MemberRow
from app.users.models import User


class DepartmentNameTakenError(ConflictError):
    def __init__(self) -> None:
        super().__init__("A department with this name already exists")


async def list_departments(session: AsyncSession, organization_id: uuid.UUID) -> list[Department]:
    result = await session.scalars(
        select(Department)
        .where(Department.organization_id == organization_id)
        .order_by(Department.name)
    )
    return list(result)


async def get_department(
    session: AsyncSession, organization_id: uuid.UUID, department_id: uuid.UUID
) -> Department:
    department = await session.scalar(
        select(Department).where(
            Department.organization_id == organization_id, Department.id == department_id
        )
    )
    if department is None:
        raise NotFoundError("Department")
    return department


async def create_department(
    session: AsyncSession, organization_id: uuid.UUID, name: str
) -> Department:
    department = Department(organization_id=organization_id, name=name)
    session.add(department)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == DEPARTMENT_NAME_UNIQUE_INDEX:
            raise DepartmentNameTakenError from exc
        raise
    return department


async def _get_membership(
    session: AsyncSession, organization_id: uuid.UUID, membership_id: uuid.UUID
) -> Membership:
    membership = await session.scalar(
        select(Membership).where(
            Membership.organization_id == organization_id, Membership.id == membership_id
        )
    )
    if membership is None:
        raise NotFoundError("Member")
    return membership


async def list_department_members(
    session: AsyncSession, organization_id: uuid.UUID, department_id: uuid.UUID
) -> list[MemberRow]:
    await get_department(session, organization_id, department_id)
    result = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .join(
            DepartmentMember,
            (DepartmentMember.organization_id == Membership.organization_id)
            & (DepartmentMember.membership_id == Membership.id),
        )
        .where(
            DepartmentMember.organization_id == organization_id,
            DepartmentMember.department_id == department_id,
        )
        .order_by(User.full_name)
    )
    return [(membership, user) for membership, user in result]


async def add_department_member(
    session: AsyncSession,
    organization_id: uuid.UUID,
    department_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> None:
    """Idempotent: adding someone who is already in the department is a no-op."""
    await get_department(session, organization_id, department_id)
    membership = await _get_membership(session, organization_id, membership_id)
    if membership.status != MembershipStatus.ACTIVE:
        raise ConflictError("Member is deactivated")

    await session.execute(
        insert(DepartmentMember)
        .values(
            organization_id=organization_id,
            department_id=department_id,
            membership_id=membership_id,
        )
        .on_conflict_do_nothing()
    )
    await session.commit()


async def remove_department_member(
    session: AsyncSession,
    organization_id: uuid.UUID,
    department_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> None:
    """Idempotent: removing someone who isn't in the department is a no-op.

    Unknown department/member IDs (including other organizations') are still 404.
    """
    await get_department(session, organization_id, department_id)
    await _get_membership(session, organization_id, membership_id)
    await session.execute(
        delete(DepartmentMember).where(
            DepartmentMember.organization_id == organization_id,
            DepartmentMember.department_id == department_id,
            DepartmentMember.membership_id == membership_id,
        )
    )
    await session.commit()
