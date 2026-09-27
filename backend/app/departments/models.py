import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

DEPARTMENT_NAME_MAX_LENGTH = 100
DEPARTMENT_NAME_UNIQUE_INDEX = "uq_departments_organization_id_lower_name"


class Department(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),  # composite FK target
        # "IT" and "it" are the same department within an organization.
        # Note: func.lower("name") would lower the *string literal* 'name', not the column.
        Index(DEPARTMENT_NAME_UNIQUE_INDEX, "organization_id", text("lower(name)"), unique=True),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(DEPARTMENT_NAME_MAX_LENGTH))


class DepartmentMember(Base):
    """Which memberships work in which departments (N:M).

    Both composite FKs include organization_id, so the database itself refuses
    to link a department of one organization with a membership of another.
    """

    __tablename__ = "department_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "department_id"],
            ["departments.organization_id", "departments.id"],
            name="fk_department_members_department",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["memberships.organization_id", "memberships.id"],
            name="fk_department_members_membership",
            ondelete="RESTRICT",
        ),
        # "Which departments is this member in?" (PK covers department-first lookups.)
        Index("ix_department_members_organization_id_membership_id", "organization_id", "membership_id"),
    )

    department_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
