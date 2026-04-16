"""Build the explicit LangGraph StateGraph for the LangAgent Platform."""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from src.core.nodes import (
    agent_reasoning_node,
    configure_nodes,
    permission_node,
    route_after_permission,
    route_after_reasoning,
    sub_agent_monitor_node,
    tool_executor_node,
)
from src.core.state import AgentState


def build_agent_graph(
    model: Any,
    tools: list[Any] | None = None,
    permission_manager: Any = None,
    max_parallel_tools: int = 10,
) -> StateGraph:
    """Build the agent graph (uncompiled).

    Call ``.compile()`` on the result (optionally passing a checkpointer)
    to obtain a runnable ``CompiledGraph``.
    """
    tools = tools or []

    # Bind tools to the model so it can generate tool-call messages.
    bound_model = model.bind_tools(tools) if tools else model

    # Wire up module-level globals in nodes.py.
    configure_nodes(bound_model, tools, permission_manager, max_parallel_tools)

    # Build the StateGraph.
    graph = StateGraph(AgentState)

    graph.add_node("agent", agent_reasoning_node)
    graph.add_node("permission_check", permission_node)
    graph.add_node("tools", tool_executor_node)
    graph.add_node("monitor", sub_agent_monitor_node)

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        route_after_reasoning,
        {
            "permission_check": "permission_check",
            "tools": "tools",
            "__end__": END,
        },
    )
    graph.add_conditional_edges(
        "permission_check",
        route_after_permission,
        {
            "tools": "tools",
            "agent": "agent",
        },
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("monitor", "agent")

    return graph
