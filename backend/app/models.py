"""Single registry of all ORM models.

Alembic and the test suite import this module so `Base.metadata` is complete.
A model missing here would look "deleted" to autogenerate, which would emit DROP TABLE.
"""

from app.ai.models import AIToolCall, AIUsage
from app.ai.proposals.models import AIProposal, AIProposalItem
from app.auth.models import AuthSession, LoginAttempt
from app.base import Base
from app.comments.models import Comment
from app.departments.models import Department, DepartmentMember
from app.organizations.models import Membership, Organization
from app.requests.models import Request, RequestEvent
from app.users.models import User

__all__ = [
    "AIProposal",
    "AIProposalItem",
    "AIToolCall",
    "AIUsage",
    "AuthSession",
    "Base",
    "Comment",
    "Department",
    "DepartmentMember",
    "LoginAttempt",
    "Membership",
    "Organization",
    "Request",
    "RequestEvent",
    "User",
]
