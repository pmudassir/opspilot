import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.organizations.models import ORGANIZATION_NAME_MAX_LENGTH, MembershipRole
from app.users.models import NAME_MAX_LENGTH

PASSWORD_MIN_LENGTH = 12
# Upper bound stops multi-megabyte "passwords" from being fed to a deliberately slow hash.
PASSWORD_MAX_LENGTH = 128

NormalizedEmail = Annotated[EmailStr, AfterValidator(str.lower)]
Password = Annotated[str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)]
FullName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH)
]
OrganizationName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=ORGANIZATION_NAME_MAX_LENGTH
    ),
]


class _Request(BaseModel):
    # Unknown fields are rejected, e.g. a client sending {"role": "admin"} gets a 422
    # instead of the field being silently ignored.
    model_config = ConfigDict(extra="forbid")


class SignupRequest(_Request):
    email: NormalizedEmail
    password: Password
    full_name: FullName
    organization_name: OrganizationName


class LoginRequest(_Request):
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


class MeResponse(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]
