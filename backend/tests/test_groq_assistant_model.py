"""GroqAssistantModel without the network: message conversion, request shape, parsing, errors."""

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from groq import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from app.ai.assistant.groq_model import GroqAssistantModel, to_provider_message
from app.ai.assistant.model import (
    AssistantMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from app.ai.drafter import DrafterError, DraftFailure

TOOLS = [{"type": "function", "function": {"name": "list_departments", "parameters": {"type": "object", "properties": {}}}}]
REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def completion(content: str | None, tool_calls: list[Any] | None = None, finish_reason: str = "stop") -> Any:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish_reason, message=message)],
        usage=SimpleNamespace(prompt_tokens=900, completion_tokens=40),
    )


def sdk_call(call_id: str, name: str, arguments: str) -> Any:
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


class FakeCompletions:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result, self.error, self.kwargs = result, error, None

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


def model_with(completions: FakeCompletions) -> GroqAssistantModel:
    model = GroqAssistantModel(api_key="test-key", model="openai/gpt-oss-120b", timeout_seconds=5)
    model._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[assignment]
    return model


def test_messages_convert_to_the_openai_format() -> None:
    call = ToolCall("call_1", "search_requests", '{"limit": 3}')
    assert [to_provider_message(m) for m in [
        SystemMessage("rules"),
        UserMessage("question"),
        AssistantMessage(None, (call,)),
        ToolMessage("call_1", '{"ok":true}'),
    ]] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "search_requests", "arguments": '{"limit": 3}'}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"ok":true}'},
    ]


async def test_request_passes_tools_and_tool_choice() -> None:
    completions = FakeCompletions(completion("Hi"))
    await model_with(completions).complete([UserMessage("hi")], TOOLS, tool_choice="none")
    assert completions.kwargs is not None
    assert completions.kwargs["tools"] == TOOLS
    assert completions.kwargs["tool_choice"] == "none"
    assert completions.kwargs["reasoning_effort"] == "low" and completions.kwargs["include_reasoning"] is False


async def test_without_tools_neither_tools_nor_tool_choice_are_sent() -> None:
    # The forced final answer: no tool definitions, so the model can't try to call one.
    completions = FakeCompletions(completion("Here's what I found."))
    await model_with(completions).complete([UserMessage("hi")], [], tool_choice="none")
    assert completions.kwargs is not None
    assert "tools" not in completions.kwargs and "tool_choice" not in completions.kwargs


async def test_tool_calls_are_parsed_but_not_trusted() -> None:
    result = completion(None, [sdk_call("c1", "search_requests", '{"status": ["nonsense"]}')], "tool_calls")
    turn = await model_with(FakeCompletions(result)).complete([UserMessage("q")], TOOLS, tool_choice="auto")
    # Raw arguments are passed through as text: validating them is the executor's job.
    assert turn.tool_calls == (ToolCall("c1", "search_requests", '{"status": ["nonsense"]}'),)
    assert turn.text is None and turn.usage.input_tokens == 900


async def test_text_answer() -> None:
    turn = await model_with(FakeCompletions(completion("  Two requests are open.  "))).complete(
        [UserMessage("q")], TOOLS, tool_choice="auto"
    )
    assert turn.text == "Two requests are open." and turn.tool_calls == ()


@pytest.mark.parametrize("response", [completion("cut off", finish_reason="length"), completion(None), completion("  ")])
async def test_unusable_responses_are_rejected(response: Any) -> None:
    with pytest.raises(DrafterError) as caught:
        await model_with(FakeCompletions(response)).complete([UserMessage("q")], TOOLS, tool_choice="auto")
    assert caught.value.failure == DraftFailure.INVALID_OUTPUT


@pytest.mark.parametrize(
    ("error", "failure"),
    [
        (APITimeoutError(request=REQUEST), DraftFailure.TIMEOUT),
        (RateLimitError("limit", response=httpx.Response(429, headers={"retry-after": "7"}, request=REQUEST), body=None), DraftFailure.RATE_LIMITED),
        (APIConnectionError(request=REQUEST), DraftFailure.PROVIDER_ERROR),
        (APIStatusError("bad", response=httpx.Response(500, request=REQUEST), body=None), DraftFailure.PROVIDER_ERROR),
        (
            APIStatusError("bad", response=httpx.Response(400, request=REQUEST), body={"error": {"code": "tool_use_failed"}}),
            DraftFailure.INVALID_OUTPUT,
        ),
    ],
)
async def test_sdk_errors_map_to_failures(error: Exception, failure: DraftFailure) -> None:
    with pytest.raises(DrafterError) as caught:
        await model_with(FakeCompletions(error=error)).complete([UserMessage("q")], TOOLS, tool_choice="auto")
    assert caught.value.failure == failure
