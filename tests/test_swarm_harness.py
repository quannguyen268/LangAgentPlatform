"""Test HarnessRunner — phase state machine."""
import pytest
from src.swarm.harness import HarnessRunner
from src.swarm.phases import (
    ArtifactRequiredGate,
    HumanApprovalGate,
    HarnessContext,
)


@pytest.mark.asyncio
async def test_advances_when_gate_passes(tmp_path):
    (tmp_path / "plan.md").write_text("ok")
    runner = HarnessRunner(
        phases=["plan", "execute"],
        gates={"plan": ArtifactRequiredGate("plan.md")},
    )
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())

    assert runner.current_phase == "plan"
    advanced = await runner.try_advance(ctx)
    assert advanced is True
    assert runner.current_phase == "execute"


@pytest.mark.asyncio
async def test_blocks_when_gate_fails(tmp_path):
    runner = HarnessRunner(
        phases=["plan", "execute"],
        gates={"plan": ArtifactRequiredGate("plan.md")},
    )
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())
    advanced = await runner.try_advance(ctx)
    assert advanced is False
    assert runner.current_phase == "plan"


@pytest.mark.asyncio
async def test_is_finished_after_last_phase(tmp_path):
    runner = HarnessRunner(
        phases=["a", "b"],
        gates={"a": HumanApprovalGate(key="a"), "b": HumanApprovalGate(key="b")},
    )
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals={"a", "b"})

    await runner.try_advance(ctx)  # a → b
    await runner.try_advance(ctx)  # b → finished
    assert runner.is_finished


@pytest.mark.asyncio
async def test_no_gate_means_always_advance(tmp_path):
    """A phase without a configured gate advances freely."""
    runner = HarnessRunner(phases=["a", "b"], gates={})
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())
    advanced = await runner.try_advance(ctx)
    assert advanced is True
    assert runner.current_phase == "b"
