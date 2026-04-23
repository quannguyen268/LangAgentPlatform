"""Phase gates — block phase transitions until conditions are met (GAP-5).

Each ``PhaseGate`` is an async check that returns a ``GateResult``. The harness
runner evaluates the configured gates for a phase and advances only when every
gate returns ``passed=True``.

Defaults are fail-closed: a gate whose prerequisites are missing (e.g.
``AllTasksCompleteGate`` with ``ctx.registry is None``) blocks the transition
rather than silently passing.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..subagent.registry import SubAgentRegistry
from ..subagent.state import SubAgentState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str = ""


@dataclass
class HarnessContext:
    """Context passed to each ``PhaseGate.check()``.

    ``approvals`` is intentionally a plain ``set`` so the harness can mutate it
    (e.g. when an operator approves via the API). Gates must treat it as
    read-only by convention.
    """
    workspace: str
    registry: Optional[SubAgentRegistry]
    approvals: set[str] = field(default_factory=set)


class PhaseGate(ABC):
    """Async precondition check for advancing a phase."""

    @abstractmethod
    async def check(self, ctx: HarnessContext) -> GateResult: ...


class ArtifactRequiredGate(PhaseGate):
    """Passes iff the artifact file exists as a regular file inside the workspace.

    Path-traversal hardening: ``artifact`` must be a workspace-relative path.
    Absolute paths are rejected at construction time; any relative path that
    resolves outside the workspace (via ``..`` segments or symlinks) fails the
    gate with an explicit reason. Directories do not satisfy the gate.
    """

    def __init__(self, artifact: str):
        if not artifact:
            raise ValueError("ArtifactRequiredGate: artifact path must not be empty")
        if Path(artifact).is_absolute():
            raise ValueError(
                f"ArtifactRequiredGate: artifact must be workspace-relative, got {artifact!r}"
            )
        self._artifact = artifact

    async def check(self, ctx: HarnessContext) -> GateResult:
        try:
            ws = Path(ctx.workspace).resolve()
            p = (ws / self._artifact).resolve()
        except OSError as e:
            return GateResult(False, f"Artifact path resolution failed: {e}")

        if not p.is_relative_to(ws):
            return GateResult(
                False, f"Artifact path escapes workspace: {self._artifact}"
            )
        if p.is_file():
            return GateResult(True)
        return GateResult(False, f"Required artifact missing: {self._artifact}")


class AllTasksCompleteGate(PhaseGate):
    """Passes iff every registered agent has reached ``SubAgentState.FINISHED``.

    Fail-closed: with no registry attached, the gate blocks. FAILED, BLOCKED,
    and still-running agents all keep the gate closed; the reason string
    buckets them by state so operators can see what is holding the phase.
    """

    async def check(self, ctx: HarnessContext) -> GateResult:
        if ctx.registry is None:
            return GateResult(False, "AllTasksCompleteGate: no registry attached")
        agents = ctx.registry.list_agents()
        if not agents:
            return GateResult(True, "No agents registered")

        by_state: dict[SubAgentState, list[str]] = defaultdict(list)
        for a in agents:
            if a.state != SubAgentState.FINISHED:
                by_state[a.state].append(a.agent_id)

        if not by_state:
            return GateResult(True)

        parts = [
            f"{state.value}: [{', '.join(ids)}]"
            for state, ids in sorted(by_state.items(), key=lambda kv: kv[0].value)
        ]
        return GateResult(False, "Agents not finished — " + "; ".join(parts))


class HumanApprovalGate(PhaseGate):
    """Passes once ``ctx.approvals`` contains the configured key."""

    def __init__(self, key: str):
        if not key:
            raise ValueError("HumanApprovalGate: key must not be empty")
        self._key = key

    async def check(self, ctx: HarnessContext) -> GateResult:
        if self._key in ctx.approvals:
            return GateResult(True)
        return GateResult(False, f"Awaiting human approval for '{self._key}'")
