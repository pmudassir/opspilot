"""Provider-agnostic interface for a model that can ask for tools.

The model never runs anything: a ModelTurn either answers in text or *describes*
tool calls, which the runner hands to the executor. Implementations:
GroqAssistantModel (real), ScriptedModel (tests).
Failures reuse the drafting errors (DrafterError + DraftFailure): same provider, same meanings.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.ai.drafter import TokenUsage

ToolChoice = Literal["auto", "none"]


@dataclass(frozen=True)
class ToolCall:
    id: str  # provider's call id: the tool result must answer this id
    name: str
    arguments: str  # raw JSON text, NOT yet validated


@dataclass(frozen=True)
class ModelTurn:
    text: str | None
    tool_calls: tuple[ToolCall, ...]
    usage: TokenUsage


@dataclass(frozen=True)
class SystemMessage:
    content: str


@dataclass(frozen=True)
class UserMessage:
    content: str


@dataclass(frozen=True)
class AssistantMessage:
    content: str | None
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ToolMessage:
    tool_call_id: str
    content: str


Message = SystemMessage | UserMessage | AssistantMessage | ToolMessage


class ToolCallingModel(Protocol):
    provider: str
    model: str

    async def complete(
        self, messages: list[Message], tools: list[dict[str, Any]], *, tool_choice: ToolChoice
    ) -> ModelTurn:
        """Raise DrafterError on any provider failure or unusable output."""
        ...
