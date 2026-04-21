"""Test orchestration tools: spawn_agent, recall_agent, monitor_agents, etc."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from langgraph.store.memory import InMemoryStore


def test_tools_imports():
    from src.subagent.tools import (
        init_orchestration_tools,
        spawn_agent,
        recall_agent,
        monitor_agents,
        assign_task,
        switch_agent_model,
        review_cost,
    )
    assert spawn_agent is not None


@pytest.mark.asyncio
async def test_spawn_agent_registers():
    """spawn_agent should create an AgentInfo and register it."""
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import SubAgentState
    from src.subagent.tools import init_orchestration_tools, spawn_agent

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    # Mock the spawner that creates the actual asyncio task
    async def mock_spawner(info, **kwargs):
        async def dummy():
            await asyncio.sleep(0.01)
        return asyncio.create_task(dummy())

    init_orchestration_tools(registry=registry, spawner=mock_spawner, cost_tracker=None)

    result = await spawn_agent.ainvoke({
        "name": "researcher",
        "role": "executor",
        "task": "Research topic X",
        "tools": ["web_search"],
        "tier": "standard",
    })

    assert "agent-" in result  # Returns the agent_id
    agents = registry.list_agents()
    assert len(agents) == 1
    assert agents[0].name == "researcher"
    assert agents[0].role == "executor"

    # Clean up
    await registry.deregister(agents[0].agent_id)


@pytest.mark.asyncio
async def test_monitor_agents_returns_status():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo
    from src.subagent.tools import init_orchestration_tools, monitor_agents

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="researcher", role="executor",
        task="Research", tier="standard", tools=["web_search"], skills=[],
    )
    registry.register(info, t)

    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=None)
    result = await monitor_agents.ainvoke({})
    assert "researcher" in result
    assert "a1" in result or "executor" in result

    await t


@pytest.mark.asyncio
async def test_monitor_agents_empty():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.tools import init_orchestration_tools, monitor_agents

    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=None)
    result = await monitor_agents.ainvoke({})
    assert "No active" in result or "no" in result.lower()


@pytest.mark.asyncio
async def test_recall_agent():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo
    from src.subagent.tools import init_orchestration_tools, recall_agent

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    t = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="researcher", role="executor",
        task="Research", tier="standard", tools=[], skills=[],
    )
    registry.register(info, t)

    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=None)
    result = await recall_agent.ainvoke({"agent_id": "a1"})
    assert "recalled" in result.lower() or "a1" in result
    await asyncio.sleep(0.1)
    assert registry.get_agent("a1") is None


@pytest.mark.asyncio
async def test_recall_agent_not_found():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.tools import init_orchestration_tools, recall_agent

    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=None)
    result = await recall_agent.ainvoke({"agent_id": "nonexistent"})
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_switch_agent_model():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo
    from src.subagent.tools import init_orchestration_tools, switch_agent_model

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    t = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="researcher", role="executor",
        task="Research", tier="standard", tools=[], skills=[],
    )
    registry.register(info, t)

    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=None)
    result = await switch_agent_model.ainvoke({"agent_id": "a1", "tier": "advanced"})
    assert "advanced" in result
    assert registry.get_agent("a1").tier == "advanced"

    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_review_cost():
    from src.observability.cost import CostTracker
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.tools import init_orchestration_tools, review_cost

    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    tracker = CostTracker()
    tracker.record(provider="anthropic", model="claude-sonnet-4-6",
                   prompt_tokens=1000, completion_tokens=500,
                   user_id="u1", tier="standard")

    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=tracker)
    result = await review_cost.ainvoke({})
    assert "cost" in result.lower() or "tokens" in result.lower()


@pytest.mark.asyncio
async def test_review_cost_no_tracker():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.tools import init_orchestration_tools, review_cost

    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=None)
    result = await review_cost.ainvoke({})
    assert "not initialized" in result.lower() or "no" in result.lower()


@pytest.mark.asyncio
async def test_assign_task():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo
    from src.subagent.tools import init_orchestration_tools, assign_task

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    t = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="researcher", role="executor",
        task="Research", tier="standard", tools=[], skills=[],
    )
    registry.register(info, t)

    init_orchestration_tools(registry=registry, spawner=None, cost_tracker=None)
    result = await assign_task.ainvoke({"agent_id": "a1", "task": "New task"})
    assert "a1" in result or "assigned" in result.lower()

    # Inbox should have the message
    inbox = await registry.agent_store.drain_inbox("a1")
    assert len(inbox) == 1
    assert "New task" in inbox[0]["message"]

    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass
