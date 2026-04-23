"""Test RecoveryExecutor — actually perform retry/escalate/reassign/abort."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from langgraph.store.memory import InMemoryStore

from src.subagent.broadcaster import EventBroadcaster
from src.subagent.recovery import RecoveryChain, RecoveryAction
from src.subagent.recovery_executor import RecoveryExecutor
from src.subagent.registry import SubAgentRegistry
from src.subagent.state import AgentInfo, SubAgentState


def _spawner_stub():
    """A spawn() that immediately returns a finished task."""
    async def spawn(info, recovery_context=None):
        async def noop():
            return
        return asyncio.create_task(noop())
    m = MagicMock()
    m.spawn = AsyncMock(side_effect=spawn)
    return m


@pytest.mark.asyncio
async def test_recovery_retry_increments_retry_count():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    spawner = _spawner_stub()
    executor = RecoveryExecutor(
        registry=registry,
        chain=RecoveryChain(max_retries=1),
        spawner=spawner,
        broadcaster=EventBroadcaster(None),
    )

    async def placeholder():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(placeholder())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    info.retry_count = 0
    registry.register(info, t)

    await executor.handle_failure("a1", reason="stale_heartbeat")
    assert registry.get_agent("a1").retry_count == 1
    spawner.spawn.assert_awaited()


@pytest.mark.asyncio
async def test_recovery_escalate_bumps_tier():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    spawner = _spawner_stub()
    executor = RecoveryExecutor(
        registry=registry,
        chain=RecoveryChain(max_retries=1),
        spawner=spawner,
        broadcaster=EventBroadcaster(None),
    )

    async def placeholder():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(placeholder())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    info.retry_count = 1  # → ESCALATE per RecoveryChain logic
    registry.register(info, t)

    await executor.handle_failure("a1", reason="iteration_limit")
    assert registry.get_agent("a1").tier == "advanced"


@pytest.mark.asyncio
async def test_recovery_abort_removes_agent():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    spawner = _spawner_stub()
    executor = RecoveryExecutor(
        registry=registry,
        chain=RecoveryChain(max_retries=1),
        spawner=spawner,
        broadcaster=EventBroadcaster(None),
    )

    async def placeholder():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(placeholder())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="expert", tools=[], skills=[],
    )
    info.retry_count = 10  # → ABORT
    registry.register(info, t)

    await executor.handle_failure("a1", reason="task_timeout")
    assert registry.get_agent("a1") is None
