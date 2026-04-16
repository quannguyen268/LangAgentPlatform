"""Graph nodes and routing functions for the LangAgent StateGraph."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level globals — configured once by ``configure_nodes``.
# ---------------------------------------------------------------------------
_model: Any = None
_tools_by_name: dict[str, Any] = {}
_permission_manager: Any = None
_max_parallel_tools: int = 10


def configure_nodes(
    model: Any,
    tools: list[Any],
    permission_manager: Any = None,
    max_parallel_tools: int = 10,
) -> None:
    """Set module globals. Called once by ``build_agent_graph``."""
    global _model, _tools_by_name, _permission_manager, _max_parallel_tools
    _model = model
    _tools_by_name = {t.name: t for t in tools} if tools else {}
    _permission_manager = permission_manager
    _max_parallel_tools = max_parallel_tools


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def agent_reasoning_node(state: dict) -> dict:
    """Call LLM with messages. Return {"messages": [response]}."""
    response = await _model.ainvoke(state["messages"])
    return {"messages": [response]}


async def permission_node(state: dict) -> dict:
    """Check permissions for pending tool calls.

    For now this is a pass-through; full enforcement arrives in a later phase.
    """
    return {}


async def tool_executor_node(state: dict) -> dict:
    """Execute tool calls from the last AI message in parallel (with semaphore)."""
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None) or []

    if not tool_calls:
        return {"messages": []}

    semaphore = asyncio.Semaphore(_max_parallel_tools)

    async def _run_one(tc: dict) -> ToolMessage:
        async with semaphore:
            name = tc["name"]
            args = tc.get("args", {})
            tool_call_id = tc["id"]
            tool = _tools_by_name.get(name)

            if tool is None:
                return ToolMessage(
                    content=f"Error: tool '{name}' not found",
                    tool_call_id=tool_call_id,
                    name=name,
                )

            try:
                # Prefer async invocation; fall back to sync via thread.
                if hasattr(tool, "ainvoke"):
                    result = await tool.ainvoke(args)
                else:
                    result = await asyncio.to_thread(tool.invoke, args)

                content = str(result) if not isinstance(result, str) else result
            except Exception as exc:  # noqa: BLE001
                logger.exception("Tool %s raised an error", name)
                content = f"Error executing {name}: {exc}"

            return ToolMessage(
                content=content,
                tool_call_id=tool_call_id,
                name=name,
            )

    results = await asyncio.gather(*[_run_one(tc) for tc in tool_calls])
    return {"messages": list(results)}


async def sub_agent_monitor_node(state: dict) -> dict:
    """Placeholder for Phase 1C sub-agent monitoring."""
    return {}


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def route_after_reasoning(state: dict) -> str:
    """Route after the agent reasoning node.

    If the last message contains tool calls, route to permission check
    (or directly to tools if there is no permission manager).
    Otherwise route to ``__end__``.
    """
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "permission_check" if _permission_manager else "tools"
    return "__end__"


def route_after_permission(state: dict) -> str:
    """Route after the permission node. Always routes to tools for now."""
    return "tools"
