"""Test context recovery prompt builder (GAP-1)."""
import pytest
from langgraph.store.memory import InMemoryStore


@pytest.mark.asyncio
async def test_context_recovery_imports():
    from src.subagent.context_recovery import build_recovery_context
    assert build_recovery_context is not None


@pytest.mark.asyncio
async def test_build_recovery_context_with_progress():
    from src.subagent.context_recovery import build_recovery_context
    from src.subagent.store import AgentStore

    store = InMemoryStore()
    agent_store = AgentStore(store)

    await agent_store.write_config("a1", {"role": "executor", "task": "Build REST API"})
    await agent_store.write_progress("a1", message="Designed schema, 3/5 endpoints done", cost=1.2)

    ctx = await build_recovery_context(
        agent_id="a1",
        role="executor",
        store=store,
    )
    assert "executor" in ctx
    assert "3/5 endpoints" in ctx


@pytest.mark.asyncio
async def test_build_recovery_no_data():
    from src.subagent.context_recovery import build_recovery_context

    store = InMemoryStore()
    ctx = await build_recovery_context(agent_id="nonexistent", role="executor", store=store)
    # Should still return a string, not crash
    assert "executor" in ctx
    assert isinstance(ctx, str)


@pytest.mark.asyncio
async def test_build_recovery_includes_iteration():
    from src.subagent.context_recovery import build_recovery_context
    from src.subagent.store import AgentStore

    store = InMemoryStore()
    agent_store = AgentStore(store)
    await agent_store.write_heartbeat("a1", iteration=12, status="running")

    ctx = await build_recovery_context(agent_id="a1", role="executor", store=store)
    assert "12" in ctx or "iteration" in ctx.lower()


@pytest.mark.asyncio
async def test_evaluator_sees_team_status():
    """Evaluators see all agents' status, executors only their own."""
    from src.subagent.context_recovery import build_recovery_context
    from src.subagent.store import AgentStore

    store = InMemoryStore()
    agent_store = AgentStore(store)
    await agent_store.write_config("a1", {"role": "evaluator", "task": "Review code"})

    # Seed other agents' progress
    await agent_store.write_progress("other-1", message="Worker 1 done", cost=0)
    await agent_store.write_progress("other-2", message="Worker 2 running", cost=0)

    ctx = await build_recovery_context(
        agent_id="a1",
        role="evaluator",
        store=store,
        all_agent_ids=["other-1", "other-2"],
    )
    assert "Team status" in ctx or "other-1" in ctx or "Worker" in ctx
