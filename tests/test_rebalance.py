"""Test TaskRebalancer — redistribute pending inbox tasks from dead agents."""
import asyncio
import pytest
from unittest.mock import AsyncMock
from langgraph.store.memory import InMemoryStore

from src.subagent.rebalance import TaskRebalancer
from src.subagent.registry import SubAgentRegistry
from src.subagent.state import AgentInfo


async def _placeholder_task():
    async def placeholder():
        await asyncio.sleep(0.01)
    return asyncio.create_task(placeholder())


def _agent(agent_id, role="executor"):
    return AgentInfo(
        agent_id=agent_id, name=f"n-{agent_id}", role=role, task="t",
        tier="standard", tools=[], skills=[],
    )


@pytest.mark.asyncio
async def test_rebalances_to_same_role():
    registry = SubAgentRegistry(InMemoryStore())
    rebalancer = TaskRebalancer(registry)

    registry.register(_agent("dead"), await _placeholder_task())
    await registry.agent_store.send_inbox("dead", sender="master", message="task 1")
    await registry.agent_store.send_inbox("dead", sender="master", message="task 2")

    registry.register(_agent("live"), await _placeholder_task())

    moved = await rebalancer.rebalance_from("dead")
    assert moved == 2
    inbox = await registry.agent_store.drain_inbox("live")
    assert len(inbox) == 2
    # Sender rewrite preserves original origin
    assert all(m["from"].startswith("rebalanced-from:dead:master") for m in inbox)

    await registry.shutdown_all()


@pytest.mark.asyncio
async def test_round_robin_across_multiple_survivors():
    """With 2 survivors + 3 messages, round-robin gives idx 0,2 → A, idx 1 → B."""
    registry = SubAgentRegistry(InMemoryStore())
    rebalancer = TaskRebalancer(registry)

    registry.register(_agent("dead"), await _placeholder_task())
    for i in range(3):
        await registry.agent_store.send_inbox("dead", sender="master", message=f"m{i}")

    registry.register(_agent("live_a"), await _placeholder_task())
    registry.register(_agent("live_b"), await _placeholder_task())

    moved = await rebalancer.rebalance_from("dead")
    assert moved == 3

    inbox_a = await registry.agent_store.drain_inbox("live_a")
    inbox_b = await registry.agent_store.drain_inbox("live_b")
    # Candidate ordering is list_agents() order: live_a registered first.
    # Round-robin: idx 0→a, idx 1→b, idx 2→a.
    assert [m["message"] for m in inbox_a] == ["m0", "m2"]
    assert [m["message"] for m in inbox_b] == ["m1"]

    await registry.shutdown_all()


@pytest.mark.asyncio
async def test_no_compatible_agent_returns_zero():
    registry = SubAgentRegistry(InMemoryStore())
    rebalancer = TaskRebalancer(registry)

    registry.register(_agent("dead", role="planner"), await _placeholder_task())
    await registry.agent_store.send_inbox("dead", sender="master", message="task 1")

    moved = await rebalancer.rebalance_from("dead")
    assert moved == 0

    await registry.shutdown_all()


@pytest.mark.asyncio
async def test_empty_inbox_is_noop():
    registry = SubAgentRegistry(InMemoryStore())
    rebalancer = TaskRebalancer(registry)

    registry.register(_agent("dead"), await _placeholder_task())

    moved = await rebalancer.rebalance_from("dead")
    assert moved == 0

    await registry.shutdown_all()


@pytest.mark.asyncio
async def test_unknown_dead_agent_returns_zero_without_draining():
    """Missing dead agent must short-circuit before any store I/O."""
    registry = SubAgentRegistry(InMemoryStore())
    rebalancer = TaskRebalancer(registry)

    # Spy on agent_store to confirm no drain call happened
    real_drain = registry.agent_store.drain_inbox
    calls: list[str] = []

    async def spy_drain(agent_id):
        calls.append(agent_id)
        return await real_drain(agent_id)

    registry.agent_store.drain_inbox = spy_drain  # type: ignore[method-assign]

    moved = await rebalancer.rebalance_from("ghost")
    assert moved == 0
    assert calls == []


@pytest.mark.asyncio
async def test_send_failure_requeues_to_dead_inbox():
    """If send_inbox raises mid-loop, failed messages return to the dead agent's inbox."""
    registry = SubAgentRegistry(InMemoryStore())
    rebalancer = TaskRebalancer(registry)

    registry.register(_agent("dead"), await _placeholder_task())
    await registry.agent_store.send_inbox("dead", sender="master", message="m0")
    await registry.agent_store.send_inbox("dead", sender="master", message="m1")

    registry.register(_agent("live"), await _placeholder_task())

    # Patch send_inbox to fail only when delivering to "live"; succeed otherwise
    # (so the re-queue to the dead inbox still works).
    real_send = registry.agent_store.send_inbox

    async def flaky_send(agent_id, *, sender, message):
        if agent_id == "live":
            raise RuntimeError("transient store failure")
        return await real_send(agent_id, sender=sender, message=message)

    registry.agent_store.send_inbox = flaky_send  # type: ignore[method-assign]

    moved = await rebalancer.rebalance_from("dead")
    assert moved == 0  # both sends failed

    # Restore real send and drain the dead inbox — both messages re-queued
    registry.agent_store.send_inbox = real_send  # type: ignore[method-assign]
    requeued = await registry.agent_store.drain_inbox("dead")
    assert len(requeued) == 2
    # Original sender preserved on re-queue
    assert all(m["from"] == "master" for m in requeued)

    await registry.shutdown_all()
