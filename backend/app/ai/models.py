import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
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
        UniqueConstraint("organization_id", "id"),  # composite FK target (ai_tool_calls)
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


class ToolCallStatus(StrEnum):
    OK = "ok"
    REPEATED = "repeated"
    INVALID_ARGUMENTS = "invalid_arguments"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    AMBIGUOUS = "ambiguous"
    UNKNOWN_TOOL = "unknown_tool"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


class AIToolCall(UUIDPrimaryKeyMixin, Base):
    """One tool call the assistant model asked for, and what happened to it.
    Metadata only: arguments and results hold user-written text and are not stored."""

    __tablename__ = "ai_tool_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["ai_usage.organization_id", "ai_usage.id"],
            name="fk_ai_tool_calls_run",
            ondelete="RESTRICT",
        ),
        Index("ix_ai_tool_calls_org_run", "organization_id", "run_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"))
    run_id: Mapped[uuid.UUID]  # the run's ai_usage row
    step: Mapped[int] = mapped_column(SmallInteger)
    tool: Mapped[str] = mapped_column(String(64))
    status: Mapped[ToolCallStatus] = mapped_column(str_enum_column_type(ToolCallStatus, name="ai_tool_call_status"))
    latency_ms: Mapped[int] = mapped_column(Integer)
    result_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
