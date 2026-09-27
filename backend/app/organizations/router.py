import uuid

from fastapi import APIRouter, status

from app.db import SessionDep
from app.organizations import service
from app.organizations.schemas import (
    AddMemberRequest,
    MemberOut,
    OrganizationOut,
    UpdateMemberRequest,
)
from app.permissions import Permission
from app.tenancy import authorized

router = APIRouter(prefix="/api/v1/orgs/{org_id}", tags=["organizations"])


@router.get("")
async def get_organization(
    context: authorized(Permission.ORGANIZATION_READ),  # type: ignore[valid-type]
) -> OrganizationOut:
    return OrganizationOut(id=context.organization.id, name=context.organization.name)


@router.get("/members")
async def list_members(
    context: authorized(Permission.MEMBERS_READ),  # type: ignore[valid-type]
    session: SessionDep,
) -> list[MemberOut]:
    rows = await service.list_members(session, context.organization_id)
    return [MemberOut.from_row(membership, user) for membership, user in rows]


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    body: AddMemberRequest,
    context: authorized(Permission.MEMBERS_MANAGE),  # type: ignore[valid-type]
    session: SessionDep,
) -> MemberOut:
    membership, user = await service.add_member(
        session,
        context.organization_id,
        email=body.email,
        full_name=body.full_name,
        password=body.password,
        role=body.role,
    )
    return MemberOut.from_row(membership, user)


@router.patch("/members/{membership_id}")
async def update_member(
    membership_id: uuid.UUID,
    body: UpdateMemberRequest,
    context: authorized(Permission.MEMBERS_MANAGE),  # type: ignore[valid-type]
    session: SessionDep,
) -> MemberOut:
    membership, user = await service.update_member(
        session, context.organization_id, membership_id, role=body.role, status=body.status
    )
    return MemberOut.from_row(membership, user)
