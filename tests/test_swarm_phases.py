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


@pytest.mark.asyncio
async def test_all_tasks_gate_fail_closed_on_missing_registry():
    """No registry should block (fail-closed), not silently pass."""
    gate = AllTasksCompleteGate()
    ctx = HarnessContext(workspace="", registry=None, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is False
    assert "no registry" in result.reason.lower()


@pytest.mark.asyncio
async def test_all_tasks_gate_empty_registry_passes():
    """Empty registry (no agents ever registered) is vacuously complete."""
    registry = SubAgentRegistry(InMemoryStore())
    gate = AllTasksCompleteGate()
    ctx = HarnessContext(workspace="", registry=registry, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is True


@pytest.mark.asyncio
async def test_all_tasks_gate_failed_agent_blocks_with_bucketed_reason():
    """FAILED agents are terminal but not successful — gate must block, and
    the reason must separate failed from running so operators can triage."""
    registry = SubAgentRegistry(InMemoryStore())

    async def ph():
        await asyncio.sleep(0.01)

    # a_ok: FINISHED (should not appear in reason)
    # a_bad: FAILED (should appear bucketed as "failed")
    # a_run: still SPAWNING (should appear bucketed as "spawning")
    for agent_id, final_state in [
        ("a_ok", SubAgentState.FINISHED),
        ("a_bad", SubAgentState.FAILED),
        ("a_run", SubAgentState.SPAWNING),
    ]:
        t = asyncio.create_task(ph())
        info = AgentInfo(
            agent_id=agent_id, name=agent_id, role="executor", task="t",
            tier="standard", tools=[], skills=[],
        )
        registry.register(info, t)
        registry.update_state(agent_id, final_state)

    gate = AllTasksCompleteGate()
    ctx = HarnessContext(workspace="", registry=registry, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is False
    assert "failed" in result.reason.lower()
    assert "a_bad" in result.reason
    assert "a_run" in result.reason
    # Finished agent not mentioned in the reason
    assert "a_ok" not in result.reason


def test_artifact_gate_rejects_absolute_path():
    with pytest.raises(ValueError, match="workspace-relative"):
        ArtifactRequiredGate(artifact="/etc/passwd")


def test_artifact_gate_rejects_empty_name():
    with pytest.raises(ValueError, match="must not be empty"):
        ArtifactRequiredGate(artifact="")


@pytest.mark.asyncio
async def test_artifact_gate_rejects_path_traversal(tmp_path):
    """`../outside` must not escape the workspace even if the target exists."""
    # Create a file outside the workspace
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("x")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    gate = ArtifactRequiredGate(artifact="../outside/secret.txt")
    ctx = HarnessContext(workspace=str(workspace), registry=None, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is False
    assert "escapes workspace" in result.reason


@pytest.mark.asyncio
async def test_artifact_gate_rejects_directory(tmp_path):
    """A directory at the artifact path does not satisfy the gate."""
    (tmp_path / "plan.md").mkdir()
    gate = ArtifactRequiredGate(artifact="plan.md")
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())
    result = await gate.check(ctx)
    assert result.passed is False


def test_human_approval_gate_rejects_empty_key():
    with pytest.raises(ValueError, match="must not be empty"):
        HumanApprovalGate(key="")
