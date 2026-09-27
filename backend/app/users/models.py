from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

EMAIL_MAX_LENGTH = 320
NAME_MAX_LENGTH = 200
PASSWORD_HASH_MAX_LENGTH = 255


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Global identity. Holds nothing organization-specific — that lives on Membership."""

    __tablename__ = "users"
    __table_args__ = (
        # Emails are normalized to lowercase by the app; the DB guarantees it,
        # which makes the plain UNIQUE constraint case-insensitive in effect.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True)
    full_name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    password_hash: Mapped[str] = mapped_column(String(PASSWORD_HASH_MAX_LENGTH))
