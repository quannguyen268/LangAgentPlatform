"""HarnessRunner — walks a team through a list of phases, gated by PhaseGate."""
from __future__ import annotations

import logging
from typing import Optional

from .phases import HarnessContext, PhaseGate

logger = logging.getLogger(__name__)


class HarnessRunner:
    """Lightweight phase state machine."""

    def __init__(self, phases: list[str], gates: dict[str, PhaseGate]):
        if not phases:
            raise ValueError("HarnessRunner requires at least one phase")
        self._phases = list(phases)
        self._gates = gates
        self._index = 0

    @property
    def current_phase(self) -> Optional[str]:
        if self.is_finished:
            return None
        return self._phases[self._index]

    @property
    def is_finished(self) -> bool:
        return self._index >= len(self._phases)

    async def try_advance(self, ctx: HarnessContext) -> bool:
        """If the current phase's gate passes, advance. Return whether we advanced."""
        if self.is_finished:
            return False
        phase = self._phases[self._index]
        gate = self._gates.get(phase)
        if gate is None:
            # No gate configured — advance freely
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
