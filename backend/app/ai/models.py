import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.base import Base, UUIDPrimaryKeyMixin, str_enum_column_type


class AIUsageOutcome(StrEnum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PROVIDER_ERROR = "provider_error"
    INVALID_OUTPUT = "invalid_output"


class AIUsage(UUIDPrimaryKeyMixin, Base):
    """One AI call: observability (latency, tokens, outcome), cost tracking and the
    per-member quota. Stores no prompt text or output: nothing user-written is retained."""

    __tablename__ = "ai_usage"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["memberships.organization_id", "memberships.id"],
            name="fk_ai_usage_membership",
            ondelete="RESTRICT",
        ),
        # Quota: a member's calls in the last hour.
        Index("ix_ai_usage_org_membership_created", "organization_id", "membership_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"))
    membership_id: Mapped[uuid.UUID]
    feature: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[AIUsageOutcome] = mapped_column(str_enum_column_type(AIUsageOutcome, name="ai_usage_outcome"))
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
