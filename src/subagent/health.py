"""HealthMonitor — 3-layer failure detection for sub-agents.

Layers:
- Heartbeat: stale heartbeat (>120s by default)
- Task timeout: asyncio.Task running too long (>30min by default)
- Iteration limit: too many tool-call cycles (>50 by default)
"""
from __future__ import annotations

import logging
import time
from enum import Enum

from .registry import SubAgentRegistry
from .state import SubAgentState

logger = logging.getLogger(__name__)


class FailureReason(str, Enum):
    STALE_HEARTBEAT = "stale_heartbeat"
    TASK_TIMEOUT = "task_timeout"
    ITERATION_LIMIT = "iteration_limit"


class HealthMonitor:
    """Detect failing sub-agents via heartbeat, timeout, and iteration limits."""

    def __init__(
        self,
        registry: SubAgentRegistry,
        heartbeat_timeout: float = 120.0,     # seconds
        task_timeout: float = 1800.0,          # seconds (30 min)
        max_iterations: int = 50,
    ):
        self._registry = registry
        self._heartbeat_timeout = heartbeat_timeout
        self._task_timeout = task_timeout
        self._max_iterations = max_iterations

    def check_agent(self, agent_id: str) -> FailureReason | None:
        """Check one agent. Returns failure reason or None if healthy."""
        info = self._registry.get_agent(agent_id)
        if info is None:
            return None

        # Skip terminal states
        if info.state in (SubAgentState.FINISHED, SubAgentState.FAILED):
            return None

        now = time.time()

        # Iteration limit check
        if info.iteration > self._max_iterations:
            return FailureReason.ITERATION_LIMIT

        # Task timeout check
        if (now - info.created_at) > self._task_timeout:
            return FailureReason.TASK_TIMEOUT

        # Heartbeat check (only applies if agent is past SPAWNING)
        if info.state != SubAgentState.SPAWNING:
            if (now - info.last_heartbeat) > self._heartbeat_timeout:
                return FailureReason.STALE_HEARTBEAT

        return None

    def check_all(self) -> dict[str, FailureReason]:
        """Check all registered agents. Returns dict of unhealthy agents."""
        results: dict[str, FailureReason] = {}
        for info in self._registry.list_agents():
            reason = self.check_agent(info.agent_id)
            if reason is not None:
                results[info.agent_id] = reason
        return results
