"""RequestDrafter backed by Groq (free tier), using strict JSON-schema structured outputs."""

import json
import logging
from typing import Any, Literal

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    RateLimitError,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.drafter import DrafterError, DraftFailure, ModelDraft, TokenUsage
from app.ai.prompts import SYSTEM_PROMPT, user_message
from app.requests.models import RequestPriority

logger = logging.getLogger(__name__)

TITLE_MAX = 200
DESCRIPTION_MAX = 5000
RATIONALE_MAX = 500
MAX_OUTPUT_TOKENS = 1024


def draft_schema(departments: list[str]) -> dict[str, Any]:
    """Strict-mode schema: every property required, no extra properties, and the department
    constrained to this organization's department names (or null)."""
    department: dict[str, Any] = (
        {"anyOf": [{"type": "string", "enum": departments}, {"type": "null"}]}
        if departments
        else {"type": "null"}
    )
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "department": department,
            "priority": {"type": "string", "enum": [p.value for p in RequestPriority]},
            "rationale": {"type": "string"},
        },
        "required": ["title", "description", "department", "priority", "rationale"],
        "additionalProperties": False,
    }


class _Output(BaseModel):
    """Second line of defence: validate the JSON even though the schema was enforced."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: str = Field(max_length=DESCRIPTION_MAX)
    department: str | None
    priority: Literal["low", "normal", "high", "urgent"]
    rationale: str = Field(max_length=RATIONALE_MAX)


class GroqDrafter:
    provider = "groq"

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float) -> None:
        self.model = model
        # One retry: a user is waiting, and Groq's 429s carry a retry-after we surface instead.
        self._client = AsyncGroq(api_key=api_key, timeout=timeout_seconds, max_retries=1)

    async def draft(self, *, text: str, departments: list[str]) -> ModelDraft:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message(text, departments)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "request_draft", "strict": True, "schema": draft_schema(departments)},
                },
                reasoning_effort="low",  # a routing decision doesn't need deep reasoning
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
        except (APIStatusError, APIConnectionError) as exc:
            logger.warning("AI provider error: %s", type(exc).__name__)
            raise DrafterError(DraftFailure.PROVIDER_ERROR, "The AI provider returned an error") from exc

        return self._parse(response)

    def _parse(self, response: Any) -> ModelDraft:
        choice = response.choices[0]
        usage = TokenUsage(
            input_tokens=getattr(response.usage, "prompt_tokens", None),
            output_tokens=getattr(response.usage, "completion_tokens", None),
        )
        if choice.finish_reason != "stop" or not choice.message.content:
            raise DrafterError(DraftFailure.INVALID_OUTPUT, f"Unusable response ({choice.finish_reason})")
        try:
            output = _Output.model_validate(json.loads(choice.message.content))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise DrafterError(DraftFailure.INVALID_OUTPUT, "The AI returned a malformed draft") from exc
        return ModelDraft(
            title=output.title,
            description=output.description,
            department=output.department,
            priority=RequestPriority(output.priority),
            rationale=output.rationale,
            usage=usage,
        )
