"""Test SubAgentRegistry — tracks active sub-agents."""
import asyncio
import pytest
from langgraph.store.memory import InMemoryStore


@pytest.mark.asyncio
async def test_registry_imports():
    from src.subagent.registry import SubAgentRegistry
    assert SubAgentRegistry is not None


@pytest.mark.asyncio
async def test_registry_empty():
    from src.subagent.registry import SubAgentRegistry
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    assert registry.list_agents() == []
    assert registry.get_agent("missing") is None


@pytest.mark.asyncio
async def test_register_and_get():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo, SubAgentState

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy_task():
        await asyncio.sleep(0.01)

    task = asyncio.create_task(dummy_task())
    info = AgentInfo(
        agent_id="agent-1", name="researcher", role="executor",
        task="Test", tier="standard", tools=[], skills=[],
    )
    registry.register(info, task)

    got = registry.get_agent("agent-1")
    assert got is info

    await task  # Clean up


@pytest.mark.asyncio
async def test_list_agents():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(0.01)

    t1 = asyncio.create_task(dummy())
    t2 = asyncio.create_task(dummy())

    info1 = AgentInfo(agent_id="a1", name="n1", role="executor", task="t1", tier="standard", tools=[], skills=[])
    info2 = AgentInfo(agent_id="a2", name="n2", role="planner", task="t2", tier="advanced", tools=[], skills=[])
    registry.register(info1, t1)
    registry.register(info2, t2)

    agents = registry.list_agents()
    assert len(agents) == 2
    assert {a.agent_id for a in agents} == {"a1", "a2"}

    await asyncio.gather(t1, t2)


@pytest.mark.asyncio
async def test_update_state():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo, SubAgentState

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(dummy())
    info = AgentInfo(agent_id="a1", name="n1", role="executor", task="t", tier="standard", tools=[], skills=[])
    registry.register(info, t)

    registry.update_state("a1", SubAgentState.RUNNING)
    assert registry.get_agent("a1").state == SubAgentState.RUNNING

    await t


@pytest.mark.asyncio
async def test_deregister_cancels_task():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def long_running():
        await asyncio.sleep(10)

    t = asyncio.create_task(long_running())
    info = AgentInfo(agent_id="a1", name="n1", role="executor", task="t", tier="standard", tools=[], skills=[])
    registry.register(info, t)

    await registry.deregister("a1")
    # Give time for cancellation
    await asyncio.sleep(0.05)
    assert registry.get_agent("a1") is None
    assert t.cancelled() or t.done()


@pytest.mark.asyncio
async def test_deregister_nonexistent():
    from src.subagent.registry import SubAgentRegistry
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    # Should not raise
    await registry.deregister("missing")


@pytest.mark.asyncio
async def test_filter_by_state():
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo, SubAgentState

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(0.01)

    for i in range(3):
        t = asyncio.create_task(dummy())
        info = AgentInfo(agent_id=f"a{i}", name=f"n{i}", role="executor", task="t", tier="standard", tools=[], skills=[])
        registry.register(info, t)

    registry.update_state("a0", SubAgentState.RUNNING)
    registry.update_state("a1", SubAgentState.FINISHED)
    # a2 stays SPAWNING

    running = registry.filter_by_state(SubAgentState.RUNNING)
    assert len(running) == 1
    assert running[0].agent_id == "a0"

    finished = registry.filter_by_state(SubAgentState.FINISHED)
    assert len(finished) == 1

    # Clean up all tasks
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_shutdown_all_cancels_every_agent():
    """shutdown_all deregisters every agent and cancels their tasks."""
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def long_running():
        await asyncio.sleep(10)

    tasks = []
    for i in range(3):
        t = asyncio.create_task(long_running())
        tasks.append(t)
        info = AgentInfo(
            agent_id=f"a{i}", name=f"n{i}", role="executor",
            task="t", tier="standard", tools=[], skills=[],
        )
        registry.register(info, t)

    assert len(registry.list_agents()) == 3
    await registry.shutdown_all()
    assert registry.list_agents() == []
    # All tasks should have been cancelled
    await asyncio.sleep(0.05)
    assert all(t.cancelled() or t.done() for t in tasks)


@pytest.mark.asyncio
async def test_shutdown_all_on_empty_registry():
    """shutdown_all is safe when no agents are registered."""
    from src.subagent.registry import SubAgentRegistry

    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    # Should not raise
    await registry.shutdown_all()
    assert registry.list_agents() == []
