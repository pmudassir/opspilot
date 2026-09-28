"""Single registry of all ORM models.

Alembic and the test suite import this module so `Base.metadata` is complete.
A model missing here would look "deleted" to autogenerate, which would emit DROP TABLE.
"""

from app.auth.models import AuthSession
from app.base import Base
from app.comments.models import Comment
from app.departments.models import Department, DepartmentMember
from app.organizations.models import Membership, Organization
from app.requests.models import Request, RequestEvent
from app.users.models import User

__all__ = [
    "AuthSession",
    "Base",
    "Comment",
    "Department",
    "DepartmentMember",
    "Membership",
    "Organization",
    "Request",
    "RequestEvent",
    "User",
]
