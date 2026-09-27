"""Single registry of all ORM models.

Alembic and the test suite import this module so `Base.metadata` is complete.
A model missing here would look "deleted" to autogenerate, which would emit DROP TABLE.
"""

from app.base import Base
from app.organizations.models import Membership, Organization
from app.users.models import User

__all__ = ["Base", "Membership", "Organization", "User"]
