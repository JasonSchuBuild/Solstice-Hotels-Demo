"""Tiny tool registry.

A tool = a JSON schema the model sees + a Python handler that does the work.
Handlers receive a ToolContext (who is asking, what they're allowed to see) and
return a dict. Decorate a function with @tool(...) to register it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolContext:
    agent: str                      # "concierge" | "group_sales"
    mode: str                       # "guest" | "staff"
    session_id: str
    verified_guest_id: str | None = None
    failed_verifications: int = 0
    transcript: list[dict] = field(default_factory=list)   # [{role, text}] for handoffs


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., dict]
    agents: tuple[str, ...]          # which agents get this tool
    modes: tuple[str, ...] = ("guest", "staff")

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, properties: dict, required: list[str] | None = None,
         agents: tuple[str, ...] = ("concierge",), modes: tuple[str, ...] = ("guest", "staff")):
    def wrap(fn):
        TOOLS[name] = Tool(name, description,
                           {"type": "object", "properties": properties, "required": required or []},
                           fn, agents, modes)
        return fn
    return wrap


class ToolError(Exception):
    """Raised by a handler for an expected refusal (e.g. not verified). Shown to the model as an error."""


def attach_data_warnings(ctx: ToolContext, out: dict, *record_ids: str) -> dict:
    """If any record this tool touched has a known data issue, tell the model
    (so it doesn't trust that field) and raise an alert for the data owner."""
    from solstice.data.quality import raise_alerts
    from solstice.data.store import get_store
    store = get_store()
    warnings = store.warnings_for(*record_ids)
    if warnings:
        out["data_quality_warnings"] = warnings
        raise_alerts(store.data_issues, list(record_ids), ctx.session_id, triggered_by=f"{ctx.agent}/{ctx.mode}")
    return out


def tools_for(agent: str, mode: str) -> list[Tool]:
    # Import modules so their @tool decorators run.
    from solstice.tools import concierge_tools, group_tools, escalation, data_quality_tools  # noqa: F401
    return [t for t in TOOLS.values() if agent in t.agents and mode in t.modes]
