"""Role → permission map (ADR: fixed roles in code, not a roles table).

The single place that answers "may this role do X?". Routes ask for a permission,
never for a role, so changing what a role may do is a one-line edit here.
"""

from enum import StrEnum

from app.organizations.models import MembershipRole


class Permission(StrEnum):
    ORGANIZATION_READ = "organization:read"
    DEPARTMENTS_READ = "departments:read"
    DEPARTMENTS_MANAGE = "departments:manage"
    MEMBERS_READ = "members:read"
    MEMBERS_MANAGE = "members:manage"
    REQUESTS_CREATE = "requests:create"
    # Every role may read requests; members only see their own (see REQUESTS_READ_ALL).
    REQUESTS_READ = "requests:read"
    REQUESTS_READ_ALL = "requests:read_all"
    REQUESTS_COMMENT = "requests:comment"
    # Assign, reassign and unassign anyone in the request's department.
    REQUESTS_ASSIGN = "requests:assign"
    # Take an OPEN request in one of your own departments.
    REQUESTS_CLAIM = "requests:claim"
    # Start/complete requests assigned to you; *_ANY lifts the "assigned to you" condition.
    REQUESTS_WORK = "requests:work"
    REQUESTS_WORK_ANY = "requests:work_any"
    # Cancel any non-terminal request (requesters may always cancel their own while OPEN).
    REQUESTS_CANCEL_ANY = "requests:cancel_any"
    METRICS_READ = "metrics:read"


_EVERYONE = frozenset(
    {
        Permission.ORGANIZATION_READ,
        Permission.DEPARTMENTS_READ,
        Permission.REQUESTS_CREATE,
        Permission.REQUESTS_READ,
        Permission.REQUESTS_COMMENT,
    }
)
_STAFF = _EVERYONE | {
    Permission.MEMBERS_READ,
    Permission.REQUESTS_READ_ALL,
    Permission.REQUESTS_CLAIM,
    Permission.REQUESTS_WORK,
}
_SUPERVISORS = _STAFF | {
    Permission.REQUESTS_ASSIGN,
    Permission.REQUESTS_WORK_ANY,
    Permission.REQUESTS_CANCEL_ANY,
    Permission.METRICS_READ,
}

ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.MEMBER: _EVERYONE,
    MembershipRole.AGENT: _STAFF,
    MembershipRole.MANAGER: _SUPERVISORS,
    MembershipRole.ADMIN: _SUPERVISORS | {Permission.MEMBERS_MANAGE, Permission.DEPARTMENTS_MANAGE},
}


def has_permission(role: MembershipRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
