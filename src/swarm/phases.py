"""Phase gates — block phase transitions until conditions are met (GAP-5)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..subagent.registry import SubAgentRegistry
from ..subagent.state import SubAgentState


@dataclass
class GateResult:
    passed: bool
    reason: str = ""


@dataclass
class HarnessContext:
    """Context passed to each PhaseGate.check()."""
    workspace: str
    registry: Optional[SubAgentRegistry]
    approvals: set[str] = field(default_factory=set)


class PhaseGate(ABC):
    @abstractmethod
    async def check(self, ctx: HarnessContext) -> GateResult: ...


class ArtifactRequiredGate(PhaseGate):
    """Passes iff an artifact file exists in the workspace."""

    def __init__(self, artifact: str):
        self._artifact = artifact

    async def check(self, ctx: HarnessContext) -> GateResult:
        p = Path(ctx.workspace) / self._artifact
        if p.exists():
            return GateResult(True)
        return GateResult(False, f"Required artifact missing: {self._artifact}")


class AllTasksCompleteGate(PhaseGate):
    """Passes iff every registered agent is FINISHED."""

    async def check(self, ctx: HarnessContext) -> GateResult:
        if ctx.registry is None:
            return GateResult(True, "No registry — treating as complete")
        agents = ctx.registry.list_agents()
        if not agents:
            return GateResult(True, "No agents registered")
        pending = [a for a in agents if a.state != SubAgentState.FINISHED]
        if pending:
            return GateResult(
                False,
                f"{len(pending)} agent(s) not finished: " + ", ".join(a.agent_id for a in pending),
            )
        return GateResult(True)


class HumanApprovalGate(PhaseGate):
    """Passes once ``ctx.approvals`` contains the configured key."""

    def __init__(self, key: str):
        self._key = key

    async def check(self, ctx: HarnessContext) -> GateResult:
        if self._key in ctx.approvals:
            return GateResult(True)
        return GateResult(False, f"Awaiting human approval for '{self._key}'")
