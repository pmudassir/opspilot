"""Runs one tool call the model asked for, safely.

The model proposes a call; this module decides whether and how it runs:
  1. the tool must exist                                       → unknown_tool
  2. arguments must validate (strict Pydantic, no extra fields) → invalid_arguments
  3. an identical earlier call returns its earlier result       → repeated (no re-query)
  4. a short READ ONLY transaction with a statement timeout:
       - the caller's membership is reloaded (deactivated → the whole run stops, 404)
       - the permission is re-checked with the fresh role       → forbidden
       - the tool runs with the server's org id and the user's visibility
  5. timeouts and unexpected errors become safe error results  → timeout / internal

Each call opens and closes its own transaction, so no database connection is held
while waiting on the model.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assistant.refs import RefRegistry
from app.ai.assistant.registry import TOOLS
from app.ai.assistant.tools import ToolEnv, ToolError, ToolErrorCode
from app.ai.models import ToolCallStatus
from app.ai.proposals.service import ProposalDraft
from app.errors import NotFoundError
from app.organizations.models import Membership, MembershipStatus
from app.permissions import Permission, has_permission
from app.requests.service import get_request, viewer_for

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_SECONDS = 3.0
# The database gives up first (clean error, connection stays usable); the asyncio
# timeout is the backstop for anything that isn't a slow query.
ASYNCIO_TIMEOUT_MARGIN_SECONDS = 0.5
QUERY_CANCELED_SQLSTATE = "57014"
TOOL_NAME_MAX_LENGTH = 64

T = TypeVar("T")


@dataclass(frozen=True)
class ToolCallRecord:
    """Metadata for the audit log: no arguments, no results (they hold user text)."""

    tool: str
    status: ToolCallStatus
    latency_ms: int
    result_count: int | None


@dataclass(frozen=True)
class ToolOutcome:
    content: str  # JSON returned to the model
    record: ToolCallRecord


class MembershipRevokedError(NotFoundError):
    """The caller lost access mid-run: stop everything, like TenantContext would (404)."""

    def __init__(self) -> None:
        super().__init__("Organization")


def _dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _describe(exc: ValidationError) -> str:
    """Field-level messages without echoing input values."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: {error['msg']}"
        for error in exc.errors(include_input=False, include_url=False)[:5]
    )


def _is_statement_timeout(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == QUERY_CANCELED_SQLSTATE or (
        getattr(exc.orig.__cause__, "sqlstate", None) == QUERY_CANCELED_SQLSTATE
    )


class ToolExecutor:
    """One per assistant run. Deliberately stateful: it owns the run's refs and the
    results of earlier calls (for repeat detection)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        organization_id: uuid.UUID,
        membership_id: uuid.UUID,
        refs: RefRegistry,
        run_id: uuid.UUID,
        timeout_seconds: float = TOOL_TIMEOUT_SECONDS,
    ) -> None:
        self._session = session
        self._organization_id = organization_id
        self._membership_id = membership_id
        self._refs = refs
        self._run_id = run_id
        self._timeout_seconds = timeout_seconds
        self._results: dict[str, dict[str, Any]] = {}
        self._proposal: tuple[uuid.UUID, ProposalDraft] | None = None

    @property
    def proposal(self) -> tuple[uuid.UUID, ProposalDraft] | None:
        """The run's proposal draft (id, draft), if a propose_* tool made one. The
        executor never stores it: the service does, together with the run record."""
        return self._proposal

    async def execute(self, name: str, arguments: str) -> ToolOutcome:
        started = time.perf_counter()
        status, content, count = await self._execute(name, arguments)
        record = ToolCallRecord(
            tool=name[:TOOL_NAME_MAX_LENGTH],
            status=status,
            latency_ms=round((time.perf_counter() - started) * 1000),
            result_count=count,
        )
        logger.info(
            # %r: the tool name comes from the model; a newline in it must not forge a log line.
            "assistant tool call run=%s tool=%r status=%s latency_ms=%d",
            self._run_id, record.tool, record.status, record.latency_ms,
        )
        return ToolOutcome(content, record)

    async def register_request(self, request_id: uuid.UUID) -> str:
        """The request the user is looking at, as R1. 404 unless visible to them."""

        async def visible(env: ToolEnv) -> str:
            row = await get_request(env.session, env.organization_id, request_id, viewer_for(env.membership))
            return env.refs.ref_for(row.request.id)

        return await self._in_read_only_transaction(Permission.REQUESTS_READ, visible)

    async def _execute(self, name: str, arguments: str) -> tuple[ToolCallStatus, str, int | None]:
        tool = TOOLS.get(name)
        if tool is None:
            return self._error(
                ToolCallStatus.UNKNOWN_TOOL, f"No tool named {name[:TOOL_NAME_MAX_LENGTH]!r}; use one of the listed tools."
            )
        try:
            args = tool.args_model.model_validate_json(arguments.strip() or "{}")
        except ValidationError as exc:
            return self._error(ToolCallStatus.INVALID_ARGUMENTS, _describe(exc))

        if self._session.in_transaction():
            # The caller must not hold a transaction (and a connection) across model calls.
            raise RuntimeError("ToolExecutor needs a session without an open transaction")

        key = f"{tool.name}:{args.model_dump_json()}"
        if key in self._results:
            return ToolCallStatus.REPEATED, _dumps({"ok": True, "repeated": True, "data": self._results[key]}), None
        if tool.proposes and self._proposal is not None:
            return self._error(
                ToolCallStatus.FORBIDDEN, "Only one proposal per question: the user must approve or reject P1 first."
            )

        try:
            async with asyncio.timeout(self._timeout_seconds + ASYNCIO_TIMEOUT_MARGIN_SECONDS):
                result = await self._in_read_only_transaction(tool.permission, lambda env: tool.run(env, args))
        except ToolError as exc:
            return self._error(ToolCallStatus(exc.code.value), exc.message)
        except MembershipRevokedError:
            raise
        except TimeoutError:
            return await self._failed(ToolCallStatus.TIMEOUT, "The lookup took too long; try a narrower search.")
        except DBAPIError as exc:
            if _is_statement_timeout(exc):
                return await self._failed(ToolCallStatus.TIMEOUT, "The lookup took too long; try a narrower search.")
            logger.exception("assistant tool failed run=%s tool=%r", self._run_id, tool.name)
            return await self._failed(ToolCallStatus.INTERNAL, "The lookup failed.")
        except Exception:
            logger.exception("assistant tool failed run=%s tool=%r", self._run_id, tool.name)
            return await self._failed(ToolCallStatus.INTERNAL, "The lookup failed.")

        self._results[key] = result.data
        if result.proposal is not None:
            self._proposal = (uuid.uuid4(), result.proposal)
        return ToolCallStatus.OK, _dumps({"ok": True, "data": result.data}), result.count

    async def _in_read_only_transaction(self, permission: Permission, work: Callable[[ToolEnv], Awaitable[T]]) -> T:
        async with self._session.begin():
            # Defence in depth: even a buggy tool can't write.
            await self._session.execute(text("SET TRANSACTION READ ONLY"))
            timeout_ms = int(self._timeout_seconds * 1000)
            await self._session.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
            row = (
                await self._session.execute(
                    select(Membership, func.now())
                    .where(
                        Membership.organization_id == self._organization_id,
                        Membership.id == self._membership_id,
                        Membership.status == MembershipStatus.ACTIVE,
                    )
                    # The run's first TenantContext load is in the identity map: refresh it.
                    .execution_options(populate_existing=True)
                )
            ).first()
            if row is None:
                raise MembershipRevokedError
            membership, now = row
            if not has_permission(membership.role, permission):
                raise ToolError(ToolErrorCode.FORBIDDEN, "Your role doesn't allow this lookup.")
            return await work(ToolEnv(self._session, self._organization_id, membership, now, self._refs))

    @staticmethod
    def _error(status: ToolCallStatus, message: str) -> tuple[ToolCallStatus, str, None]:
        return status, _dumps({"ok": False, "error": {"code": status.value, "message": message}}), None

    async def _failed(self, status: ToolCallStatus, message: str) -> tuple[ToolCallStatus, str, None]:
        if self._session.in_transaction():
            await self._session.rollback()
        return self._error(status, message)
