"""ToolCallingModel backed by Groq (OpenAI-compatible chat completions with tools).

gpt-oss models on Groq support tool use but not parallel tool calls (checked 2026-09-30),
so each turn asks for at most one tool in practice; the runner copes with more anyway.
"""

import logging
from typing import Any

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    RateLimitError,
)

from app.ai.assistant.model import (
    AssistantMessage,
    Message,
    ModelTurn,
    SystemMessage,
    ToolCall,
    ToolChoice,
    ToolMessage,
    UserMessage,
)
from app.ai.drafter import DrafterError, DraftFailure, TokenUsage

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 1024


def to_provider_message(message: Message) -> dict[str, Any]:
    match message:
        case SystemMessage(content):
            return {"role": "system", "content": content}
        case UserMessage(content):
            return {"role": "user", "content": content}
        case AssistantMessage(content, tool_calls):
            converted: dict[str, Any] = {"role": "assistant", "content": content or ""}
            if tool_calls:
                converted["tool_calls"] = [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                    for c in tool_calls
                ]
            return converted
        case ToolMessage(tool_call_id, content):
            return {"role": "tool", "tool_call_id": tool_call_id, "content": content}
    raise TypeError(f"Unknown message type {type(message).__name__}")


class GroqAssistantModel:
    provider = "groq"

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float) -> None:
        self.model = model
        self._client = AsyncGroq(api_key=api_key, timeout=timeout_seconds, max_retries=1)

    async def complete(
        self, messages: list[Message], tools: list[dict[str, Any]], *, tool_choice: ToolChoice
    ) -> ModelTurn:
        try:
            # No tools → send neither tools nor tool_choice (the API rejects tool_choice alone).
            tool_options: dict[str, Any] = {"tools": tools, "tool_choice": tool_choice} if tools else {}
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[to_provider_message(m) for m in messages],  # type: ignore[misc]
                **tool_options,
                reasoning_effort="low",
                include_reasoning=False,
                max_completion_tokens=MAX_OUTPUT_TOKENS,
            )
        except APITimeoutError as exc:
            raise DrafterError(DraftFailure.TIMEOUT, "The AI provider timed out") from exc
        except RateLimitError as exc:
            retry_after = exc.response.headers.get("retry-after")
            raise DrafterError(
                DraftFailure.RATE_LIMITED,
                "The AI provider's free-tier limit was reached",
                retry_after_seconds=int(float(retry_after)) if retry_after else None,
            ) from exc
        except APIStatusError as exc:
            # Groq rejects a malformed tool call the model generated with 400 "tool_use_failed".
            if exc.status_code == 400 and "tool_use_failed" in str(exc.body):
                raise DrafterError(DraftFailure.INVALID_OUTPUT, "The AI produced a malformed tool call") from exc
            logger.warning("AI provider error: %s %s", type(exc).__name__, exc.status_code)
            raise DrafterError(DraftFailure.PROVIDER_ERROR, "The AI provider returned an error") from exc
        except APIConnectionError as exc:
            logger.warning("AI provider error: %s", type(exc).__name__)
            raise DrafterError(DraftFailure.PROVIDER_ERROR, "The AI provider returned an error") from exc
        return self._parse(response)

    @staticmethod
    def _parse(response: Any) -> ModelTurn:
        choice = response.choices[0]
        usage = TokenUsage(
            input_tokens=getattr(response.usage, "prompt_tokens", None),
            output_tokens=getattr(response.usage, "completion_tokens", None),
        )
        if choice.finish_reason not in ("stop", "tool_calls"):
            raise DrafterError(DraftFailure.INVALID_OUTPUT, f"Unusable response ({choice.finish_reason})")
        calls = tuple(
            ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "")
            for c in (choice.message.tool_calls or [])
        )
        text = (choice.message.content or "").strip() or None
        if not calls and text is None:
            raise DrafterError(DraftFailure.INVALID_OUTPUT, "Empty response")
        return ModelTurn(text=text, tool_calls=calls, usage=usage)
