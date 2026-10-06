"""Every tool the assistant can be offered, and their model-facing definitions."""

from typing import Any

from app.ai.assistant.proposal_tools import PROPOSAL_TOOLS
from app.ai.assistant.tools import READ_TOOLS, Tool
from app.organizations.models import MembershipRole
from app.permissions import has_permission

TOOLS: dict[str, Tool] = {**READ_TOOLS, **PROPOSAL_TOOLS}


def tools_for(role: MembershipRole) -> list[Tool]:
    """Only offer what the role may use: the model can't ask for what it never saw.
    (The executor still re-checks: offering is not authorization.)"""
    return [tool for tool in TOOLS.values() if has_permission(role, tool.permission)]


def _compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic's JSON schema, with $refs inlined and titles dropped: fewer tokens per call."""
    definitions = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = definitions[node["$ref"].rsplit("/", 1)[-1]]
                return walk({**target, **{k: v for k, v in node.items() if k != "$ref"}})
            return {k: walk(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(schema)


def tool_definition(tool: Tool) -> dict[str, Any]:
    """OpenAI-compatible function definition (the format Groq accepts)."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": _compact_schema(tool.args_model.model_json_schema()),
        },
    }
