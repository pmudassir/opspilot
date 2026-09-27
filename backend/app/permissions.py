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


_EVERYONE = frozenset({Permission.ORGANIZATION_READ, Permission.DEPARTMENTS_READ})
_STAFF = _EVERYONE | {Permission.MEMBERS_READ}

ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.MEMBER: _EVERYONE,
    MembershipRole.AGENT: _STAFF,
    MembershipRole.MANAGER: _STAFF,
    MembershipRole.ADMIN: _STAFF | {Permission.MEMBERS_MANAGE, Permission.DEPARTMENTS_MANAGE},
}


def has_permission(role: MembershipRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
