import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.base import Base, UUIDPrimaryKeyMixin


class AuthSession(UUIDPrimaryKeyMixin, Base):
    """A logged-in browser session. (Named to avoid confusion with SQLAlchemy's DB session.)

    Only a SHA-256 hash of the token is stored: a leaked table can't be replayed.
    """

    __tablename__ = "auth_sessions"

    # CASCADE (unlike business data): sessions are disposable and meaningless without the user.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


IP_MAX_LENGTH = 45  # textual IPv6


class LoginAttempt(UUIDPrimaryKeyMixin, Base):
    """One sign-in attempt, for throttling (app/auth/throttling.py) and security audit.

    Global, not tenant-owned: login happens before any organization is chosen.
    Rows older than the retention period are removed by scripts/cleanup_expired.py.
    """

    __tablename__ = "login_attempts"
    __table_args__ = (
        # Throttling counts recent failures by email and by IP.
        Index("ix_login_attempts_email_created_at", "email", "created_at"),
        Index("ix_login_attempts_ip_created_at", "ip", "created_at"),
    )

    email: Mapped[str] = mapped_column(String(320))
    ip: Mapped[str] = mapped_column(String(IP_MAX_LENGTH))
    succeeded: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
