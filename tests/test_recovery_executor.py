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


def _make_executor(store=None):
    store = store or InMemoryStore()
    registry = SubAgentRegistry(store)
    spawner = _spawner_stub()
    executor = RecoveryExecutor(
        registry=registry,
        chain=RecoveryChain(max_retries=1),
        spawner=spawner,
        broadcaster=EventBroadcaster(None),
    )
    return executor, registry, spawner


def _make_info(agent_id="a1", *, tier="standard", retry_count=0):
    info = AgentInfo(
        agent_id=agent_id, name=f"n-{agent_id}", role="executor", task="t",
        tier=tier, tools=[], skills=[],
    )
    info.retry_count = retry_count
    return info


async def _placeholder_task():
    async def placeholder():
        await asyncio.sleep(0.01)
    return asyncio.create_task(placeholder())


@pytest.mark.asyncio
async def test_recovery_retry_increments_retry_count():
    executor, registry, spawner = _make_executor()
    t = await _placeholder_task()
    info = _make_info(retry_count=0)
    registry.register(info, t)

    await executor.handle_failure("a1", reason="stale_heartbeat")
    assert registry.get_agent("a1").retry_count == 1
    spawner.spawn.assert_awaited()

    # Old task cancelled, new task installed via replace_task (not the old one)
    # Cancellation may be in-flight; yield once so it lands.
    await asyncio.sleep(0)
    assert t.cancelled() or t.done()
    assert registry.get_task("a1") is not t

    # Recovery context was propagated to spawn
    assert spawner.spawn.await_args.kwargs["recovery_context"] is not None


@pytest.mark.asyncio
async def test_recovery_escalate_bumps_tier():
    executor, registry, spawner = _make_executor()
    t = await _placeholder_task()
    info = _make_info(tier="standard", retry_count=1)  # → ESCALATE
    registry.register(info, t)

    await executor.handle_failure("a1", reason="iteration_limit")
    assert registry.get_agent("a1").tier == "advanced"
    spawner.spawn.assert_awaited()


@pytest.mark.asyncio
async def test_recovery_reassign_respawns_without_tier_bump():
    """REASSIGN (Phase 2A) respawns like RETRY but does NOT change tier."""
    executor, registry, spawner = _make_executor()
    t = await _placeholder_task()
    # tier=expert (top) + retry_count=2 → no escalation path, retries<3 → REASSIGN
    info = _make_info(tier="expert", retry_count=2)
    registry.register(info, t)

    await executor.handle_failure("a1", reason="stale_heartbeat")
    spawner.spawn.assert_awaited()
    assert registry.get_agent("a1").tier == "expert"  # unchanged
    assert registry.get_agent("a1").retry_count == 3


@pytest.mark.asyncio
async def test_recovery_abort_removes_agent():
    executor, registry, spawner = _make_executor()
    t = await _placeholder_task()
    info = _make_info(tier="expert", retry_count=10)  # → ABORT
    registry.register(info, t)

    await executor.handle_failure("a1", reason="task_timeout")
    assert registry.get_agent("a1") is None
    spawner.spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_failure_noop_for_unknown_agent():
    executor, registry, spawner = _make_executor()
    await executor.handle_failure("never_registered", reason="whatever")
    spawner.spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_spawn_failure_cleans_up_and_reraises():
    """If spawner.spawn raises, the agent must not linger in SPAWNING state."""
    store = InMemoryStore()
    registry = SubAgentRegistry(store)
    spawner = MagicMock()
    spawner.spawn = AsyncMock(side_effect=RuntimeError("spawn boom"))
    executor = RecoveryExecutor(
        registry=registry,
        chain=RecoveryChain(max_retries=1),
        spawner=spawner,
        broadcaster=EventBroadcaster(None),
    )
    t = await _placeholder_task()
    info = _make_info(retry_count=0)
    registry.register(info, t)

    with pytest.raises(RuntimeError, match="spawn boom"):
        await executor.handle_failure("a1", reason="stale_heartbeat")

    # Agent is deregistered — no zombie in SPAWNING state
    assert registry.get_agent("a1") is None
    assert registry.get_task("a1") is None


@pytest.mark.asyncio
async def test_context_build_failure_falls_through(monkeypatch):
    """If build_recovery_context raises, respawn still succeeds with context=None."""
    executor, registry, spawner = _make_executor()

    async def boom(**kwargs):
        raise RuntimeError("context boom")

    import src.subagent.recovery_executor as rx
    monkeypatch.setattr(rx, "build_recovery_context", boom)

    t = await _placeholder_task()
    info = _make_info(retry_count=0)
    registry.register(info, t)

    await executor.handle_failure("a1", reason="stale_heartbeat")
    spawner.spawn.assert_awaited()
    assert spawner.spawn.await_args.kwargs["recovery_context"] is None
    # Agent still registered with replaced task
    assert registry.get_agent("a1") is not None


@pytest.mark.asyncio
async def test_replace_task_rejects_unknown_agent():
    """Registry's replace_task must not resurrect a deregistered agent."""
    registry = SubAgentRegistry(InMemoryStore())
    t = await _placeholder_task()
    with pytest.raises(KeyError):
        registry.replace_task("ghost", t)
    t.cancel()
