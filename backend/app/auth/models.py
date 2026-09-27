import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, func
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
