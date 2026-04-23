"""TaskRebalancer — redistribute dead agent's inbox to compatible survivors (GAP-4).

When ``RecoveryExecutor`` aborts an agent, its pending inbox messages are not
lost — they move to another agent in the same role. Phase 2A uses role-only
matching; Phase 3 may add skills/tools overlap scoring.
"""
from __future__ import annotations

import logging

from .registry import SubAgentRegistry

logger = logging.getLogger(__name__)


class TaskRebalancer:
    """Move inbox messages from a dead agent to compatible survivors."""

    def __init__(self, registry: SubAgentRegistry):
        self._registry = registry

    async def rebalance_from(self, dead_agent_id: str) -> int:
        """Drain the dead agent's inbox and redistribute to same-role agents.

        Returns:
            Number of messages moved. Zero if no messages, no compatible
            recipient, or dead agent unknown.
        """
        dead = self._registry.get_agent(dead_agent_id)
        if dead is None:
            return 0

        # Candidate recipients: same role, not the dead agent itself
        candidates = [
            a for a in self._registry.list_agents()
            if a.role == dead.role and a.agent_id != dead_agent_id
        ]
        if not candidates:
            logger.info("No compatible agent to rebalance %s's tasks", dead_agent_id)
            return 0

        messages = await self._registry.agent_store.drain_inbox(dead_agent_id)
        if not messages:
            return 0

        # Round-robin distribute
        for idx, msg in enumerate(messages):
            recipient = candidates[idx % len(candidates)]
            await self._registry.agent_store.send_inbox(
                recipient.agent_id,
                sender=f"rebalanced-from:{dead_agent_id}",
                message=msg.get("message", ""),
            )

        logger.info(
            "Rebalanced %d tasks from %s across %d survivors",
            len(messages), dead_agent_id, len(candidates),
        )
        return len(messages)
