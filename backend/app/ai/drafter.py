"""Provider-agnostic interface for drafting a request from free text.

The model only *suggests*: its output is validated like user input by the service,
and a human reviews and submits the draft through the normal create endpoint.
Implementations: GroqDrafter (real), FakeDrafter (tests).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.requests.models import RequestPriority


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class ModelDraft:
    """What the model returned, already parsed but NOT yet trusted."""

    title: str
    description: str
    department: str | None  # a department *name*; mapped to an id by the service
    priority: RequestPriority
    rationale: str
    usage: TokenUsage


class DraftFailure(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PROVIDER_ERROR = "provider_error"
    INVALID_OUTPUT = "invalid_output"


class DrafterError(Exception):
    def __init__(self, failure: DraftFailure, detail: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(f"{failure}: {detail}")
        self.failure = failure
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds


class RequestDrafter(Protocol):
    provider: str
    model: str

    async def draft(self, *, text: str, departments: list[str]) -> ModelDraft:
        """Raise DrafterError on any failure; never return unvalidated junk."""
        ...
