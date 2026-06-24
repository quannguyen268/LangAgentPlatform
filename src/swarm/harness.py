"""HarnessRunner — phase state machine for swarm teams.

Walks a team through an ordered list of phases. Each phase may be guarded by
a ``PhaseGate``; ``try_advance()`` advances one step iff the current phase's
gate passes (or no gate is configured for that phase).

Invariant: the phase index is monotonically non-decreasing. There is no
rewind path — once a phase is left, it cannot be re-entered.
"""
from __future__ import annotations

import logging

from .phases import HarnessContext, PhaseGate

logger = logging.getLogger(__name__)


class HarnessRunner:
    """Lightweight monotonic-forward phase state machine.

    Construction rejects empty/duplicate phase lists and any gate key that
    does not correspond to a declared phase — stale keys are almost always
    typos. The gates dict is defensively copied so caller-side mutation does
    not affect in-flight state.
    """

    def __init__(self, phases: list[str], gates: dict[str, PhaseGate]):
        if not phases:
            raise ValueError("HarnessRunner requires at least one phase")
        if len(set(phases)) != len(phases):
            raise ValueError(f"HarnessRunner: phases must be unique, got {phases}")
        unknown = set(gates) - set(phases)
        if unknown:
            raise ValueError(
                f"HarnessRunner: gates reference unknown phases: {sorted(unknown)}"
            )
        self._phases: list[str] = list(phases)
        self._gates: dict[str, PhaseGate] = dict(gates)
        self._index = 0

    @property
    def phases(self) -> tuple[str, ...]:
        """Immutable view of the configured phase sequence."""
        return tuple(self._phases)

    @property
    def current_phase(self) -> str | None:
        if self.is_finished:
            return None
        return self._phases[self._index]

    @property
    def is_finished(self) -> bool:
        return self._index >= len(self._phases)

    async def try_advance(self, ctx: HarnessContext) -> bool:
        """If the current phase's gate passes, advance. Return whether we advanced.

        Raises:
            RuntimeError: if called after ``is_finished``. Calling
                ``try_advance`` on a completed harness is a programming
                error — check ``is_finished`` first.
        """
        if self.is_finished:
            raise RuntimeError("HarnessRunner: try_advance called after all phases finished")
        phase = self._phases[self._index]
        gate = self._gates.get(phase)
        if gate is None:
            # Monotonic-forward: _index only ever increases.
            self._index += 1
            logger.info("Harness: advanced past %s (no gate)", phase)
            return True
        result = await gate.check(ctx)
        if result.passed:
            self._index += 1
            logger.info("Harness: advanced past %s", phase)
            return True
        logger.info("Harness: blocked at %s — %s", phase, result.reason)
        return False
