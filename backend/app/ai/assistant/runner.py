"""The agent loop, written by hand: ask the model, run the tools it asks for, repeat.

Bounded autonomy: at most MAX_MODEL_CALLS model calls and MAX_TOOL_CALLS tool calls
within RUN_DEADLINE_SECONDS. The last allowed model call offers no tools, so the model
must answer with what it has instead of looping.
"""

import asyncio
from dataclasses import dataclass

from app.ai.assistant.executor import ToolCallRecord, ToolExecutor
from app.ai.assistant.model import (
    AssistantMessage,
    Message,
    ModelTurn,
    SystemMessage,
    ToolCallingModel,
    ToolMessage,
)
from app.ai.drafter import DrafterError, DraftFailure, TokenUsage

MAX_MODEL_CALLS = 4
MAX_TOOL_CALLS = 6
RUN_DEADLINE_SECONDS = 30.0

# The final call offers no tools: gpt-oss may try a tool even with tool_choice="none"
# (Groq then rejects the turn), but it can't call a tool it wasn't given.
_ANSWER_NOW = (
    "You have used all your lookups. Answer now from the results above; "
    "say what you couldn't check instead of guessing."
)
_BUDGET_EXHAUSTED = '{"ok":false,"error":{"code":"budget_exhausted","message":"No more lookups in this run; answer now."}}'


@dataclass(frozen=True)
class RunResult:
    answer: str
    tool_calls: tuple[ToolCallRecord, ...]
    usage: TokenUsage
    model_calls: int


class RunFailedError(Exception):
    """The run didn't produce an answer. Carries what happened so it can still be recorded."""

    def __init__(
        self,
        failure: DraftFailure,
        *,
        tool_calls: tuple[ToolCallRecord, ...],
        usage: TokenUsage,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(failure.value)
        self.failure = failure
        self.tool_calls = tool_calls
        self.usage = usage
        self.retry_after_seconds = retry_after_seconds


def _add(total: TokenUsage, turn: ModelTurn) -> TokenUsage:
    def plus(a: int | None, b: int | None) -> int | None:
        return None if a is None and b is None else (a or 0) + (b or 0)

    return TokenUsage(
        plus(total.input_tokens, turn.usage.input_tokens), plus(total.output_tokens, turn.usage.output_tokens)
    )


class _Run:
    def __init__(self, model: ToolCallingModel, executor: ToolExecutor, messages: list[Message], tools: list[dict]) -> None:
        self.model, self.executor, self.messages, self.tools = model, executor, messages, tools
        self.records: tuple[ToolCallRecord, ...] = ()
        self.usage = TokenUsage(None, None)
        self.model_calls = 0

    async def loop(self) -> str:
        while True:
            self.model_calls += 1
            must_answer = self.model_calls >= MAX_MODEL_CALLS or len(self.records) >= MAX_TOOL_CALLS
            if must_answer:
                turn = await self.model.complete([*self.messages, SystemMessage(_ANSWER_NOW)], [], tool_choice="none")
            else:
                turn = await self.model.complete(self.messages, self.tools, tool_choice="auto")
            self.usage = _add(self.usage, turn)
            if not turn.tool_calls:
                if not turn.text:
                    raise DrafterError(DraftFailure.INVALID_OUTPUT, "Empty answer")
                return turn.text
            if must_answer:
                raise DrafterError(DraftFailure.INVALID_OUTPUT, "Asked for a tool when told to answer")
            self.messages = [*self.messages, AssistantMessage(turn.text, turn.tool_calls)]
            for call in turn.tool_calls:
                # Every call id needs a reply, even the ones over budget.
                if len(self.records) >= MAX_TOOL_CALLS:
                    content = _BUDGET_EXHAUSTED
                else:
                    outcome = await self.executor.execute(call.name, call.arguments)
                    self.records = (*self.records, outcome.record)
                    content = outcome.content
                self.messages = [*self.messages, ToolMessage(call.id, content)]


async def run(
    model: ToolCallingModel,
    executor: ToolExecutor,
    *,
    messages: list[Message],
    tools: list[dict],
    deadline_seconds: float | None = None,
) -> RunResult:
    state = _Run(model, executor, messages, tools)
    try:
        async with asyncio.timeout(deadline_seconds or RUN_DEADLINE_SECONDS):
            answer = await state.loop()
    except TimeoutError as exc:
        raise RunFailedError(DraftFailure.TIMEOUT, tool_calls=state.records, usage=state.usage) from exc
    except DrafterError as exc:
        raise RunFailedError(
            exc.failure, tool_calls=state.records, usage=state.usage, retry_after_seconds=exc.retry_after_seconds
        ) from exc
    return RunResult(answer, state.records, state.usage, state.model_calls)
