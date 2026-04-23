"""Test phase gates."""
import asyncio
import pytest
from langgraph.store.memory import InMemoryStore

from src.subagent.registry import SubAgentRegistry
from src.subagent.state import AgentInfo, SubAgentState
from src.swarm.phases import (
    ArtifactRequiredGate,
    AllTasksCompleteGate,
    HumanApprovalGate,
    HarnessContext,
)


@pytest.mark.asyncio
async def test_artifact_gate_passes_when_file_exists(tmp_path):
    (tmp_path / "plan.md").write_text("content")
    gate = ArtifactRequiredGate(artifact="plan.md")
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is True


@pytest.mark.asyncio
async def test_artifact_gate_fails_when_missing(tmp_path):
    gate = ArtifactRequiredGate(artifact="plan.md")
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is False
    assert "plan.md" in result.reason


@pytest.mark.asyncio
async def test_all_tasks_complete_when_all_finished():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def ph():
        await asyncio.sleep(0.01)

    for i in range(2):
        t = asyncio.create_task(ph())
        info = AgentInfo(
            agent_id=f"a{i}", name=f"n{i}", role="executor", task="t",
            tier="standard", tools=[], skills=[],
        )
        registry.register(info, t)
        registry.update_state(f"a{i}", SubAgentState.FINISHED)

    gate = AllTasksCompleteGate()
    ctx = HarnessContext(workspace="", registry=registry, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is True


@pytest.mark.asyncio
async def test_all_tasks_complete_fails_with_running():
    store = InMemoryStore()
    registry = SubAgentRegistry(store)

    async def ph():
        await asyncio.sleep(0.01)

    t = asyncio.create_task(ph())
    info = AgentInfo(
        agent_id="a1", name="n1", role="executor", task="t",
        tier="standard", tools=[], skills=[],
    )
    registry.register(info, t)
    # Leave in SPAWNING

    gate = AllTasksCompleteGate()
    ctx = HarnessContext(workspace="", registry=registry, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is False


@pytest.mark.asyncio
async def test_human_approval_gate():
    gate = HumanApprovalGate(key="plan")
    ctx = HarnessContext(workspace="", registry=None, approvals=set())
    r1 = await gate.check(ctx)
    assert r1.passed is False

    ctx.approvals.add("plan")
    r2 = await gate.check(ctx)
    assert r2.passed is True
