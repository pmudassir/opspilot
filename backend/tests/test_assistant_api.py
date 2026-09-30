"""POST /ai/assistant end to end with a scripted model: the loop, its limits, failures,
recording, and what the model is (and isn't) shown. Tools and the database are real."""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assistant import runner
from app.ai.assistant.model import Message, ModelTurn, ToolCall, ToolChoice, ToolMessage
from app.ai.assistant.prompts import ASSISTANT_PROMPT_VERSION
from app.ai.dependencies import get_assistant_model
from app.ai.drafter import DrafterError, DraftFailure, TokenUsage
from app.ai.models import AIToolCall, AIUsage
from app.config import get_settings
from tests.helpers import (
    add_member_id,
    create_department_id,
    create_request_id,
    logged_in,
    org_url,
    signup_org,
)

UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

Step = ModelTurn | Callable[[list[Message]], ModelTurn | Awaitable[ModelTurn]]


def answer(text: str) -> ModelTurn:
    return ModelTurn(text=text, tool_calls=(), usage=TokenUsage(1000, 50))


def tool(name: str, arguments: dict[str, Any] | str | None = None, call_id: str = "c1") -> ModelTurn:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments or {})
    return ModelTurn(text=None, tool_calls=(ToolCall(call_id, name, raw),), usage=TokenUsage(800, 30))


def last_tool_result(messages: list[Message]) -> dict:
    return json.loads(next(m for m in reversed(messages) if isinstance(m, ToolMessage)).content)


@dataclass
class ScriptedModel:
    """Plays back fixed turns; a step can be a function of the conversation so far."""

    steps: list[Step]
    provider: str = "fake"
    model: str = "fake-model-1"
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def complete(self, messages: list[Message], tools: list[dict[str, Any]], *, tool_choice: ToolChoice) -> ModelTurn:
        self.calls.append({"messages": list(messages), "tools": [t["function"]["name"] for t in tools], "tool_choice": tool_choice})
        step = self.steps[min(len(self.calls), len(self.steps)) - 1]
        if isinstance(step, ModelTurn):
            return step
        result = step(messages)
        return await result if asyncio.iscoroutine(result) else result  # type: ignore[return-value]


@pytest.fixture
def model(app: FastAPI) -> ScriptedModel:
    fake = ScriptedModel(steps=[answer("Hello.")])
    app.dependency_overrides[get_assistant_model] = lambda: fake
    return fake


@dataclass(frozen=True)
class Org:
    org_id: str
    admin: AsyncClient
    clients: dict[str, AsyncClient]
    ids: dict[str, str]
    printer: str  # Mia's request
    kiosk: str  # Max's request
    other_org_request: str


@pytest.fixture
async def org(make_client: Callable[..., AsyncClient]) -> Org:
    admin = make_client()
    org_id = await signup_org(admin, email="alice@a.example", organization_name="Hotel A")
    roles = {"manager": "manager", "agent": "agent", "mia": "member", "max": "member"}
    ids = {name: await add_member_id(admin, org_id, email=f"{name}@a.example", role=role) for name, role in roles.items()}
    it = await create_department_id(admin, org_id, "IT")
    await admin.put(org_url(org_id, f"/departments/{it}/members/{ids['agent']}"))
    clients = {name: await logged_in(make_client(), f"{name}@a.example") for name in roles}
    printer = await create_request_id(clients["mia"], org_id, it, title="Printer jammed")
    kiosk = await create_request_id(clients["max"], org_id, it, title="Kiosk frozen")
    other = make_client()
    other_org = await signup_org(other, email="bob@b.example", organization_name="Hotel B")
    other_request = await create_request_id(other, other_org, await create_department_id(other, other_org, "IT"))
    return Org(org_id, admin, clients, ids, printer, kiosk, other_request)


async def ask(client: AsyncClient, org_id: str, question: str = "What's open?", **extra: Any):  # noqa: ANN201
    return await client.post(org_url(org_id, "/ai/assistant"), json={"question": question, **extra})


def answer_with_first_ref(messages: list[Message]) -> ModelTurn:
    rows = last_tool_result(messages)["data"]["requests"]
    return answer(f"{rows[0]['ref']} ({rows[0]['title']}) is open. R99 too.")


# --- happy path and what gets recorded -----------------------------------------


async def test_answers_with_tool_results_and_links_only_known_refs(
    org: Org, model: ScriptedModel, db_session: AsyncSession
) -> None:
    model.steps = [tool("search_requests", {"title_contains": "printer"}), answer_with_first_ref]
    response = await ask(org.clients["manager"], org.org_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"].startswith("R1 (Printer jammed) is open.")
    # R99 was never shown to anyone in this run: no link for it.
    assert body["references"] == [{"ref": "R1", "request_id": org.printer, "title": "Printer jammed"}]
    assert body["tools_used"] == [{"tool": "search_requests", "status": "ok"}]
    assert body["model"] == "fake-model-1" and body["as_of"]

    usage = (await db_session.scalars(select(AIUsage))).one()
    assert (usage.feature, usage.outcome, usage.prompt_version) == ("assistant", "success", ASSISTANT_PROMPT_VERSION)
    assert (usage.input_tokens, usage.output_tokens) == (1800, 80)  # summed over both model calls
    calls = (await db_session.scalars(select(AIToolCall))).all()
    assert [(c.run_id, c.step, c.tool, c.status, c.result_count) for c in calls] == [(usage.id, 1, "search_requests", "ok", 1)]


async def test_the_model_never_sees_ids_and_only_gets_the_roles_tools(org: Org, model: ScriptedModel) -> None:
    model.steps = [tool("search_requests"), answer("Done.")]
    assert (await ask(org.clients["mia"], org.org_id, request_id=org.printer)).status_code == 200
    first = model.calls[0]
    assert first["tools"] == ["search_requests", "get_request", "get_request_history", "list_departments"]
    for call in model.calls:
        for message in call["messages"]:
            assert not UUID_PATTERN.search(repr(message)), message
    system, user = first["messages"]
    assert "Mia" in system.content and "role: member" in system.content
    assert user.content.startswith("(The user is looking at request R1.)")


async def test_a_member_only_finds_their_own_requests(org: Org, model: ScriptedModel) -> None:
    seen: list[dict] = []

    def capture(messages: list[Message]) -> ModelTurn:
        seen.append(last_tool_result(messages))
        return answer("ok")

    model.steps = [tool("search_requests"), capture]
    await ask(org.clients["max"], org.org_id)
    assert [r["title"] for r in seen[0]["data"]["requests"]] == ["Kiosk frozen"]


async def test_tool_errors_go_back_to_the_model_which_can_recover(org: Org, model: ScriptedModel) -> None:
    model.steps = [
        tool("search_requests", '{"status": "open"'),  # malformed JSON
        tool("get_department_status", {"department": "IT"}),  # not offered to members
        tool("search_requests", {"status": ["open"]}),
        answer("Two open."),
    ]
    response = await ask(org.clients["mia"], org.org_id)
    assert response.status_code == 200
    assert [t["status"] for t in response.json()["tools_used"]] == ["invalid_arguments", "forbidden", "ok"]
    assert last_tool_result(model.calls[1]["messages"])["error"]["code"] == "invalid_arguments"


# --- bounded autonomy -----------------------------------------------------------


async def test_the_last_model_call_must_answer(org: Org, model: ScriptedModel) -> None:
    model.steps = [tool("list_departments"), tool("list_departments"), tool("search_requests"), answer("Best effort.")]
    response = await ask(org.clients["manager"], org.org_id)
    assert response.status_code == 200
    assert [c["tool_choice"] for c in model.calls] == ["auto", "auto", "auto", "none"]
    # The last call offers no tools at all and says why, so the model can only answer.
    assert model.calls[-1]["tools"] == []
    assert "answer now" in model.calls[-1]["messages"][-1].content.lower()
    assert [t["status"] for t in response.json()["tools_used"]] == ["ok", "repeated", "ok"]


async def test_a_model_that_ignores_the_answer_now_instruction_fails_safely(
    org: Org, model: ScriptedModel, db_session: AsyncSession
) -> None:
    model.steps = [tool("list_departments")]  # forever
    response = await ask(org.clients["manager"], org.org_id)
    assert response.status_code == 502
    assert len(model.calls) == runner.MAX_MODEL_CALLS
    usage = (await db_session.scalars(select(AIUsage))).one()
    assert usage.outcome == "invalid_output"
    assert await db_session.scalar(select(func.count()).select_from(AIToolCall)) == 3  # still recorded


async def test_tool_calls_per_run_are_capped(org: Org, model: ScriptedModel) -> None:
    many = ModelTurn(
        text=None,
        tool_calls=tuple(ToolCall(f"c{n}", "search_requests", json.dumps({"limit": n})) for n in range(1, 9)),
        usage=TokenUsage(800, 90),
    )
    model.steps = [many, answer("Enough.")]
    response = await ask(org.clients["manager"], org.org_id)
    assert response.status_code == 200
    assert len(response.json()["tools_used"]) == runner.MAX_TOOL_CALLS
    replies = [m for m in model.calls[1]["messages"] if isinstance(m, ToolMessage)]
    assert len(replies) == 8  # every call id got an answer...
    assert json.loads(replies[-1].content)["error"]["code"] == "budget_exhausted"  # ...but not a lookup
    assert model.calls[1]["tool_choice"] == "none"


async def test_the_whole_run_has_a_deadline(
    org: Org, model: ScriptedModel, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "RUN_DEADLINE_SECONDS", 0.2)

    async def slow(_: list[Message]) -> ModelTurn:
        await asyncio.sleep(2)
        return answer("too late")

    model.steps = [tool("list_departments"), slow]
    response = await ask(org.clients["manager"], org.org_id)
    assert response.status_code == 504
    usage = (await db_session.scalars(select(AIUsage))).one()
    assert usage.outcome == "timeout"


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (DraftFailure.RATE_LIMITED, 503),
        (DraftFailure.PROVIDER_ERROR, 502),
        (DraftFailure.INVALID_OUTPUT, 502),
        (DraftFailure.TIMEOUT, 504),
    ],
)
async def test_provider_failures_mid_run_are_reported_and_recorded(
    org: Org, model: ScriptedModel, db_session: AsyncSession, failure: DraftFailure, status: int
) -> None:
    def fail(_: list[Message]) -> ModelTurn:
        raise DrafterError(failure, "boom", retry_after_seconds=7 if failure == DraftFailure.RATE_LIMITED else None)

    model.steps = [tool("list_departments"), fail]
    response = await ask(org.clients["manager"], org.org_id)
    assert response.status_code == status
    assert "boom" not in response.text  # provider details stay server-side
    if failure == DraftFailure.RATE_LIMITED:
        assert response.headers["retry-after"] == "7"
    usage = (await db_session.scalars(select(AIUsage))).one()
    assert usage.outcome == failure.value
    assert await db_session.scalar(select(func.count()).select_from(AIToolCall)) == 1


async def test_losing_access_mid_run_stops_it(org: Org, model: ScriptedModel) -> None:
    async def deactivate_then_search(_: list[Message]) -> ModelTurn:
        response = await org.admin.patch(org_url(org.org_id, f"/members/{org.ids['agent']}"), json={"status": "deactivated"})
        assert response.status_code == 200
        return tool("search_requests", call_id="c2")

    model.steps = [tool("list_departments"), deactivate_then_search, answer("should not get here")]
    response = await ask(org.clients["agent"], org.org_id)
    assert response.status_code == 404
    assert len(model.calls) == 2


# --- entry checks ---------------------------------------------------------------


async def test_without_ai_configured_the_assistant_is_off(org: Org, app: FastAPI) -> None:
    app.dependency_overrides[get_assistant_model] = lambda: None
    assert (await ask(org.clients["manager"], org.org_id)).status_code == 503
    me = (await org.clients["manager"].get("/api/v1/auth/me")).json()
    assert me["features"]["ai_assistant"] is False


async def test_me_reports_the_assistant_when_configured(org: Org, model: ScriptedModel) -> None:
    me = (await org.clients["mia"].get("/api/v1/auth/me")).json()
    assert me["features"]["ai_assistant"] is True


@pytest.mark.parametrize("who", ["mia", "manager"])
async def test_a_request_in_context_must_be_visible(org: Org, model: ScriptedModel, who: str) -> None:
    hidden = org.kiosk if who == "mia" else org.other_org_request
    response = await ask(org.clients[who], org.org_id, request_id=hidden)
    assert response.status_code == 404
    assert model.calls == []


async def test_per_member_quota(org: Org, model: ScriptedModel, app: FastAPI) -> None:
    settings = get_settings().model_copy(update={"ai_assistant_runs_per_hour": 2})
    app.dependency_overrides[get_settings] = lambda: settings
    for _ in range(2):
        assert (await ask(org.clients["mia"], org.org_id)).status_code == 200
    response = await ask(org.clients["mia"], org.org_id)
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    assert len(model.calls) == 2
    assert (await ask(org.clients["max"], org.org_id)).status_code == 200  # per member


@pytest.mark.parametrize("body", [{"question": "hi"}, {"question": "x" * 501}, {"question": "What's open?", "org_id": "x"}])
async def test_input_is_validated(org: Org, model: ScriptedModel, body: dict) -> None:
    response = await org.clients["mia"].post(org_url(org.org_id, "/ai/assistant"), json=body)
    assert response.status_code == 422
    assert model.calls == []
