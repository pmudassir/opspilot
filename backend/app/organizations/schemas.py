import uuid
from typing import Self

from pydantic import BaseModel, model_validator

from app.organizations.models import Membership, MembershipRole, MembershipStatus
from app.schemas import FullName, NewPassword, NormalizedEmail, StrictRequest
from app.users.models import User


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str


class MemberOut(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: MembershipRole
    status: MembershipStatus

    @classmethod
    def from_row(cls, membership: Membership, user: User) -> Self:
        return cls(
            membership_id=membership.id,
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=membership.role,
            status=membership.status,
        )


class AddMemberRequest(StrictRequest):
    email: NormalizedEmail
    full_name: FullName
    # V1: the admin sets an initial password (no email infrastructure yet).
    password: NewPassword
    role: MembershipRole


class UpdateMemberRequest(StrictRequest):
    role: MembershipRole | None = None
    status: MembershipStatus | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if self.role is None and self.status is None:
            raise ValueError("Provide role and/or status")
        return self
