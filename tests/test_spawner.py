"""Test DeepAgentsSpawner — wires create_deep_agent into the sub-agent runtime."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from langgraph.store.memory import InMemoryStore
from langchain_core.messages import AIMessage

from src.api.websocket import EventHub
from src.subagent.broadcaster import EventBroadcaster
from src.subagent.registry import SubAgentRegistry
from src.subagent.spawner import DeepAgentsSpawner
from src.subagent.state import AgentInfo, SubAgentState


@pytest.mark.asyncio
async def test_spawner_writes_heartbeat_and_result(monkeypatch):
    """Spawner runs the inner agent and writes heartbeat + result to the store."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    hub = EventHub()
    broadcaster = EventBroadcaster(hub)

    # Patch create_deep_agent to return a mock whose ainvoke produces a single message
    inner = MagicMock()
    inner.ainvoke = AsyncMock(return_value={
        "messages": [AIMessage(content="done")],
    })
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kwargs: inner)

    spawner = DeepAgentsSpawner(
        registry=registry,
        broadcaster=broadcaster,
        base_model=MagicMock(),
        tools_by_name={},
    )

    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="do stuff",
        tier="standard", tools=[], skills=[],
    )
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))  # placeholder; will be replaced

    task = await spawner.spawn(info)
    registry._tasks["a1"] = task  # connect to registry
    await asyncio.wait_for(task, timeout=5.0)

    # Heartbeat was written
    hb = await registry.agent_store.read_heartbeat("a1")
    assert hb is not None
    # Result was written
    result = await registry.agent_store.read_result("a1")
    assert result is not None
    assert result["status"] == "success"
    # Final state should be FINISHED
    assert registry.get_agent("a1").state == SubAgentState.FINISHED


@pytest.mark.asyncio
async def test_spawner_emits_spawn_and_complete(monkeypatch):
    """Spawner emits agent_spawn and agent_complete events via broadcaster."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    hub = EventHub()
    broadcaster = EventBroadcaster(hub)

    events = []

    async def sub():
        async for ev in hub.subscribe():
            events.append(ev)
            if ev.type == "agent_complete":
                break

    sub_task = asyncio.create_task(sub())
    await asyncio.sleep(0.05)

    inner = MagicMock()
    inner.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="ok")]})
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kwargs: inner)

    spawner = DeepAgentsSpawner(
        registry=registry,
        broadcaster=broadcaster,
        base_model=MagicMock(),
        tools_by_name={},
    )
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)
    await asyncio.wait_for(sub_task, timeout=2.0)

    types = [e.type for e in events]
    assert "agent_spawn" in types
    assert "agent_complete" in types


@pytest.mark.asyncio
async def test_spawner_handles_inner_failure(monkeypatch):
    """If the inner agent raises, state becomes FAILED and an error is recorded."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    broadcaster = EventBroadcaster(None)

    inner = MagicMock()
    inner.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr("src.subagent.spawner.create_deep_agent", lambda **kwargs: inner)

    spawner = DeepAgentsSpawner(
        registry=registry, broadcaster=broadcaster,
        base_model=MagicMock(), tools_by_name={},
    )
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(info, asyncio.create_task(asyncio.sleep(0)))
    task = await spawner.spawn(info)
    registry._tasks["a1"] = task
    await asyncio.wait_for(task, timeout=5.0)

    assert registry.get_agent("a1").state == SubAgentState.FAILED
    assert "boom" in (registry.get_agent("a1").error or "")
