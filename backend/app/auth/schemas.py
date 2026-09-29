import uuid
from typing import Annotated

from pydantic import BaseModel, Field

from app.organizations.models import ORGANIZATION_NAME_MAX_LENGTH, MembershipRole
from app.permissions import Permission
from app.schemas import (
    PASSWORD_MAX_LENGTH,
    FullName,
    NewPassword,
    NormalizedEmail,
    StrictRequest,
    trimmed_str,
)


class SignupRequest(StrictRequest):
    email: NormalizedEmail
    password: NewPassword
    full_name: FullName
    organization_name: trimmed_str(ORGANIZATION_NAME_MAX_LENGTH)  # type: ignore[valid-type]


class LoginRequest(StrictRequest):
    email: NormalizedEmail
    # No length rules on login: never hint at the password policy to a guesser.
    password: Annotated[str, Field(max_length=PASSWORD_MAX_LENGTH)]


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str


class MembershipOut(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    role: MembershipRole
    # From the same role → permission map the API enforces, so the UI can decide what
    # to show without its own copy of the rules. (Showing ≠ allowing: every call is checked.)
    permissions: list[Permission]


class FeaturesOut(BaseModel):
    """Optional capabilities of this deployment (the UI hides what's off)."""

    ai_request_drafts: bool


class MeResponse(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]
    features: FeaturesOut
