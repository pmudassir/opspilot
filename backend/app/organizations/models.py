import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column_type

ORGANIZATION_NAME_MAX_LENGTH = 200


class MembershipRole(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    AGENT = "agent"
    MEMBER = "member"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant root: every tenant-owned row references an organization."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(ORGANIZATION_NAME_MAX_LENGTH))


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's identity *within* one organization. Authorization reads this, not User."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    # Indexed: Postgres does not index FK columns automatically. Needed for
    # "which orgs is this user in?" and for the RESTRICT check when deleting a user.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[MembershipRole] = mapped_column(
        str_enum_column_type(MembershipRole, name="membership_role")
    )
    status: Mapped[MembershipStatus] = mapped_column(
        str_enum_column_type(MembershipStatus, name="membership_status"),
        default=MembershipStatus.ACTIVE,
        server_default=MembershipStatus.ACTIVE.value,
    )
