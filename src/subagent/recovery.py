"""RecoveryChain — priority-chain failure recovery for sub-agents.

Chain:
  1. RETRY (same tier, new attempt with recovery context)
  2. ESCALATE (higher tier, if available)
  3. REASSIGN (different agent, different role/skills)
  4. ABORT (give up, notify user)
"""
from __future__ import annotations

import logging
from enum import Enum

from .state import AgentInfo

logger = logging.getLogger(__name__)

_TIER_ORDER = ["lite", "standard", "advanced", "expert"]


class RecoveryAction(str, Enum):
    RETRY = "retry"
    ESCALATE = "escalate"
    REASSIGN = "reassign"
    ABORT = "abort"


def next_tier(current_tier: str) -> str | None:
    """Return the next higher tier, or None if already at top."""
    try:
        idx = _TIER_ORDER.index(current_tier)
    except ValueError:
        return None
    if idx + 1 < len(_TIER_ORDER):
        return _TIER_ORDER[idx + 1]
    return None


class RecoveryChain:
    """Decide recovery action based on agent history."""

    def __init__(self, max_retries: int = 1):
        self._max_retries = max_retries

    def decide_action(self, info: AgentInfo) -> RecoveryAction:
        """Decide what action to take for a failed agent.

        Logic:
          - retry_count < max_retries → RETRY
          - Otherwise, if higher tier available and retry_count < max_retries * 2 → ESCALATE
          - Otherwise, if retry_count < max_retries * 3 → REASSIGN
          - Otherwise → ABORT
        """
        retries = info.retry_count

        # First failure at current tier → retry
        if retries < self._max_retries:
            return RecoveryAction.RETRY

        # Retries exhausted at this tier → try escalation
        higher = next_tier(info.tier)
        if higher is not None and retries < self._max_retries * 2:
            return RecoveryAction.ESCALATE

        # No higher tier or escalation also failed → reassign
        if retries < self._max_retries * 3:
            return RecoveryAction.REASSIGN

        # Give up
        return RecoveryAction.ABORT
