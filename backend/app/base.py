import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Wide enough that adding a longer enum value later needs no column-type change.
ENUM_COLUMN_LENGTH = 32

# Deterministic constraint names, so later migrations can reference (alter/drop) them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    # Server-side now(): one clock (the database), consistent within a transaction.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Fetch server-generated values via RETURNING on INSERT *and* UPDATE.
    # Otherwise they'd be expired and reloaded lazily, which async sessions forbid.
    __mapper_args__ = {"eager_defaults": True}


def str_enum_column_type(enum_cls: type[StrEnum], name: str) -> Enum:
    """VARCHAR + CHECK constraint instead of a native Postgres ENUM.

    Native ENUMs are awkward to change (values can't be removed or renamed easily);
    a CHECK constraint is replaced with an ordinary migration.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=ENUM_COLUMN_LENGTH,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )
