"""Shared request base and field types."""

from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)

from app.users.models import NAME_MAX_LENGTH

PASSWORD_MIN_LENGTH = 12
# Upper bound stops multi-megabyte "passwords" from being fed to a deliberately slow hash.
PASSWORD_MAX_LENGTH = 128


class StrictRequest(BaseModel):
    # Unknown fields are rejected, e.g. a client sending {"role": "admin"} where it isn't
    # accepted gets a 422 instead of the field being silently ignored.
    model_config = ConfigDict(extra="forbid")


def trimmed_str(max_length: int) -> type[str]:
    return Annotated[  # type: ignore[return-value]
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)
    ]


NormalizedEmail = Annotated[EmailStr, AfterValidator(str.lower)]
NewPassword = Annotated[str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)]
FullName = trimmed_str(NAME_MAX_LENGTH)
