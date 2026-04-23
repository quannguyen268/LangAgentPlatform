"""Test TaskRebalancer — redistribute pending inbox tasks from dead agents."""
import asyncio
import pytest
from langgraph.store.memory import InMemoryStore

from src.subagent.rebalance import TaskRebalancer
from src.subagent.registry import SubAgentRegistry
from src.subagent.state import AgentInfo


@pytest.mark.asyncio
async def test_rebalances_to_same_role():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    rebalancer = TaskRebalancer(registry)

    async def placeholder():
        await asyncio.sleep(0.01)

    # Dead executor
    t_dead = asyncio.create_task(placeholder())
    dead = AgentInfo(
        agent_id="dead", name="n", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(dead, t_dead)
    await registry.agent_store.send_inbox("dead", sender="master", message="task 1")
    await registry.agent_store.send_inbox("dead", sender="master", message="task 2")

    # Live executor
    t_live = asyncio.create_task(placeholder())
    live = AgentInfo(
        agent_id="live", name="n2", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(live, t_live)

    moved = await rebalancer.rebalance_from("dead")
    assert moved == 2
    # Live inbox should now have both tasks
    inbox = await registry.agent_store.drain_inbox("live")
    assert len(inbox) == 2


@pytest.mark.asyncio
async def test_no_compatible_agent_returns_zero():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    rebalancer = TaskRebalancer(registry)

    async def placeholder():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(placeholder())
    dead = AgentInfo(
        agent_id="dead", name="n", role="planner", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(dead, t)
    await registry.agent_store.send_inbox("dead", sender="master", message="task 1")

    moved = await rebalancer.rebalance_from("dead")
    assert moved == 0


@pytest.mark.asyncio
async def test_empty_inbox_is_noop():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    rebalancer = TaskRebalancer(registry)

    async def placeholder():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(placeholder())
    dead = AgentInfo(
        agent_id="dead", name="n", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(dead, t)

    moved = await rebalancer.rebalance_from("dead")
    assert moved == 0
