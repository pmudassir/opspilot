import uuid

from fastapi import APIRouter, status

from app.db import SessionDep
from app.departments import service
from app.departments.schemas import CreateDepartmentRequest, DepartmentOut
from app.organizations.schemas import MemberOut
from app.permissions import Permission
from app.tenancy import authorized

router = APIRouter(prefix="/api/v1/orgs/{org_id}/departments", tags=["departments"])


@router.get("")
async def list_departments(
    context: authorized(Permission.DEPARTMENTS_READ),  # type: ignore[valid-type]
    session: SessionDep,
) -> list[DepartmentOut]:
    departments = await service.list_departments(session, context.organization_id)
    return [DepartmentOut(id=d.id, name=d.name) for d in departments]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_department(
    body: CreateDepartmentRequest,
    context: authorized(Permission.DEPARTMENTS_MANAGE),  # type: ignore[valid-type]
    session: SessionDep,
) -> DepartmentOut:
    department = await service.create_department(session, context.organization_id, body.name)
    return DepartmentOut(id=department.id, name=department.name)


@router.get("/{department_id}/members")
async def list_department_members(
    department_id: uuid.UUID,
    context: authorized(Permission.MEMBERS_READ),  # type: ignore[valid-type]
    session: SessionDep,
) -> list[MemberOut]:
    rows = await service.list_department_members(session, context.organization_id, department_id)
    return [MemberOut.from_row(membership, user) for membership, user in rows]


@router.put("/{department_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_department_member(
    department_id: uuid.UUID,
    membership_id: uuid.UUID,
    context: authorized(Permission.DEPARTMENTS_MANAGE),  # type: ignore[valid-type]
    session: SessionDep,
) -> None:
    await service.add_department_member(
        session, context.organization_id, department_id, membership_id
    )


@router.delete(
    "/{department_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_department_member(
    department_id: uuid.UUID,
    membership_id: uuid.UUID,
    context: authorized(Permission.DEPARTMENTS_MANAGE),  # type: ignore[valid-type]
    session: SessionDep,
) -> None:
    await service.remove_department_member(
        session, context.organization_id, department_id, membership_id
    )
