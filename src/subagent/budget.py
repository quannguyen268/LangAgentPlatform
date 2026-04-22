"""BudgetEnforcer — per-agent budget checks with warn/hard thresholds."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from .state import AgentInfo


class BudgetDecision(str, Enum):
    OK = "ok"          # Under warn threshold
    WARN = "warn"      # At or above warn threshold, below hard limit
    OVER = "over"      # At or above hard limit


class BudgetEnforcer:
    """Compare an agent's running cost against a hard budget + warn threshold.

    Args:
        agent_budget_cents: hard limit in cents. ``None`` disables enforcement.
        warn_threshold: fraction of the hard limit (0.0–1.0). Cost at or above
            ``agent_budget_cents * warn_threshold`` → WARN.
    """

    def __init__(
        self,
        agent_budget_cents: Optional[float],
        warn_threshold: float = 0.8,
    ):
        self._agent_budget = agent_budget_cents
        self._warn_threshold = warn_threshold

    def check_agent(self, info: AgentInfo) -> BudgetDecision:
        if self._agent_budget is None:
            return BudgetDecision.OK
        if info.cost_cents >= self._agent_budget:
            return BudgetDecision.OVER
        if info.cost_cents >= self._agent_budget * self._warn_threshold:
            return BudgetDecision.WARN
        return BudgetDecision.OK
