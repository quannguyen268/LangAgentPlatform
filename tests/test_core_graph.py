"""Tests for the explicit LangGraph StateGraph (core/graph.py & core/nodes.py)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from langchain_core.messages import AIMessage, HumanMessage


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


def test_graph_imports():
    from src.core.graph import build_agent_graph

    assert build_agent_graph is not None


def test_nodes_import():
    from src.core.nodes import (
        agent_reasoning_node,
        permission_node,
        tool_executor_node,
    )

    assert agent_reasoning_node is not None
    assert permission_node is not None
    assert tool_executor_node is not None


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_compiles():
    from langgraph.checkpoint.memory import MemorySaver

    from src.core.graph import build_agent_graph

    mock_model = MagicMock()
    mock_model.bind_tools = MagicMock(return_value=mock_model)

    graph = build_agent_graph(model=mock_model, tools=[])
    app = graph.compile(checkpointer=MemorySaver())
    assert app is not None


# ---------------------------------------------------------------------------
# End-to-end: simple response (no tool calls)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_simple_response():
    """Graph handles a simple message with no tool calls."""
    from langgraph.checkpoint.memory import MemorySaver

    from src.core.graph import build_agent_graph

    mock_response = AIMessage(content="Hello! How can I help?")
    mock_model = MagicMock()
    mock_model.bind_tools = MagicMock(return_value=mock_model)
    mock_model.ainvoke = AsyncMock(return_value=mock_response)

    graph = build_agent_graph(model=mock_model, tools=[])
    app = graph.compile(checkpointer=MemorySaver())

    result = await app.ainvoke(
        {"messages": [HumanMessage(content="Hi")]},
        config={"configurable": {"thread_id": "test-1"}},
    )

    assert len(result["messages"]) >= 2
    assert "Hello" in result["messages"][-1].content
