"""Test HealthMonitor — 3-layer failure detection."""
import asyncio
import pytest
import time
from langgraph.store.memory import InMemoryStore


@pytest.mark.asyncio
async def test_health_imports():
    from src.subagent.health import HealthMonitor, FailureReason
    assert HealthMonitor is not None
    assert FailureReason is not None


@pytest.mark.asyncio
async def test_detect_stale_heartbeat():
    """Heartbeat older than threshold triggers STALE_HEARTBEAT."""
    from src.subagent.health import HealthMonitor, FailureReason
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo, SubAgentState

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    # Must be past SPAWNING for heartbeat check to apply
    info.state = SubAgentState.RUNNING
    # Simulate a stale heartbeat (set last_heartbeat to 200s ago)
    info.last_heartbeat = time.time() - 200
    registry.register(info, task)

    monitor = HealthMonitor(registry, heartbeat_timeout=120, task_timeout=1800, max_iterations=50)
    failure = monitor.check_agent("a1")
    assert failure == FailureReason.STALE_HEARTBEAT

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_detect_iteration_limit():
    from src.subagent.health import HealthMonitor, FailureReason
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    info.iteration = 60  # Over default limit
    info.last_heartbeat = time.time()  # Fresh heartbeat
    registry.register(info, task)

    monitor = HealthMonitor(registry, heartbeat_timeout=120, task_timeout=1800, max_iterations=50)
    failure = monitor.check_agent("a1")
    assert failure == FailureReason.ITERATION_LIMIT

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_detect_task_timeout():
    from src.subagent.health import HealthMonitor, FailureReason
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    info.created_at = time.time() - 2000  # Over task_timeout
    info.last_heartbeat = time.time()
    info.iteration = 1
    registry.register(info, task)

    monitor = HealthMonitor(registry, heartbeat_timeout=120, task_timeout=1800, max_iterations=50)
    failure = monitor.check_agent("a1")
    assert failure == FailureReason.TASK_TIMEOUT

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_healthy_agent_returns_none():
    from src.subagent.health import HealthMonitor
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    info.last_heartbeat = time.time()  # Fresh
    info.iteration = 5                  # Under limit
    info.created_at = time.time()       # Just created
    registry.register(info, task)

    monitor = HealthMonitor(registry, heartbeat_timeout=120, task_timeout=1800, max_iterations=50)
    failure = monitor.check_agent("a1")
    assert failure is None

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_check_all():
    """check_all returns dict mapping agent_id → failure_reason (only for unhealthy)."""
    from src.subagent.health import HealthMonitor
    from src.subagent.registry import SubAgentRegistry
    from src.subagent.state import AgentInfo, SubAgentState

    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def dummy():
        await asyncio.sleep(10)

    # Healthy
    t1 = asyncio.create_task(dummy())
    i1 = AgentInfo(agent_id="a1", name="n1", role="executor", task="t", tier="standard", tools=[], skills=[])
    i1.last_heartbeat = time.time()
    registry.register(i1, t1)

    # Stale — must be past SPAWNING for heartbeat check
    t2 = asyncio.create_task(dummy())
    i2 = AgentInfo(agent_id="a2", name="n2", role="executor", task="t", tier="standard", tools=[], skills=[])
    i2.state = SubAgentState.RUNNING
    i2.last_heartbeat = time.time() - 500
    registry.register(i2, t2)

    monitor = HealthMonitor(registry, heartbeat_timeout=120, task_timeout=1800, max_iterations=50)
    results = monitor.check_all()
    assert "a1" not in results
    assert "a2" in results

    t1.cancel()
    t2.cancel()
    try:
        await asyncio.gather(t1, t2)
    except asyncio.CancelledError:
        pass
