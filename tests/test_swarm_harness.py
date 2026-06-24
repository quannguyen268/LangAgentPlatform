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


def test_empty_phases_rejected():
    with pytest.raises(ValueError, match="at least one phase"):
        HarnessRunner(phases=[], gates={})


def test_duplicate_phases_rejected():
    with pytest.raises(ValueError, match="unique"):
        HarnessRunner(phases=["plan", "plan"], gates={})


def test_gate_for_unknown_phase_rejected():
    """A typo in a gate key is almost always a bug — fail loud at construction."""
    with pytest.raises(ValueError, match="unknown phases"):
        HarnessRunner(
            phases=["plan", "execute"],
            gates={"paln": HumanApprovalGate(key="x")},  # typo
        )


def test_gates_dict_is_defensively_copied():
    """Post-construction caller mutation must not leak into the runner."""
    gate = HumanApprovalGate(key="x")
    original: dict = {"plan": gate}
    runner = HarnessRunner(phases=["plan"], gates=original)
    original.clear()
    # Runner still has its own view
    assert runner._gates == {"plan": gate}  # noqa: SLF001


@pytest.mark.asyncio
async def test_try_advance_after_finished_raises(tmp_path):
    """Calling try_advance after completion is a programming error."""
    runner = HarnessRunner(phases=["a"], gates={})
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())
    assert await runner.try_advance(ctx) is True
    assert runner.is_finished
    with pytest.raises(RuntimeError, match="finished"):
        await runner.try_advance(ctx)


@pytest.mark.asyncio
async def test_mixed_gated_and_ungated_phases(tmp_path):
    """Walk a three-phase runner where the middle phase has no gate."""
    (tmp_path / "plan.md").write_text("ok")
    runner = HarnessRunner(
        phases=["plan", "execute", "verify"],
        gates={
            "plan": ArtifactRequiredGate("plan.md"),
            "verify": HumanApprovalGate(key="sign-off"),
        },
    )
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())

    assert await runner.try_advance(ctx) is True   # plan → execute (gate passes)
    assert runner.current_phase == "execute"
    assert await runner.try_advance(ctx) is True   # execute → verify (no gate)
    assert runner.current_phase == "verify"
    assert await runner.try_advance(ctx) is False  # verify blocked (no approval)
    ctx.approvals.add("sign-off")
    assert await runner.try_advance(ctx) is True   # verify → finished
    assert runner.is_finished


@pytest.mark.asyncio
async def test_blocked_reason_is_logged(tmp_path, caplog):
    runner = HarnessRunner(
        phases=["plan"],
        gates={"plan": ArtifactRequiredGate("plan.md")},
    )
    ctx = HarnessContext(workspace=str(tmp_path), registry=None, approvals=set())
    with caplog.at_level("INFO", logger="src.swarm.harness"):
        await runner.try_advance(ctx)
    assert any("blocked at plan" in r.message for r in caplog.records)
