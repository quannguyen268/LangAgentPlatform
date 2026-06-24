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

        # Candidate list is snapshotted here; further deregister-during-loop is
        # harmless because SubAgentRegistry is single-loop (see its docstring).
        # Round-robin distribute; preserve original sender so downstream filters
        # by origin still work. Per-message try/except so a single send failure
        # does not silently drop the rest of the drained inbox.
        moved = 0
        failed: list[dict] = []
        for idx, msg in enumerate(messages):
            recipient = candidates[idx % len(candidates)]
            origin = msg.get("from", "unknown")
            try:
                await self._registry.agent_store.send_inbox(
                    recipient.agent_id,
                    sender=f"rebalanced-from:{dead_agent_id}:{origin}",
                    message=msg.get("message", ""),
                )
                moved += 1
            except Exception as e:
                logger.exception(
                    "Rebalance send failed (msg %d → %s): %s",
                    idx, recipient.agent_id, e,
                )
                failed.append(msg)

        # Re-queue failures to the dead agent's inbox so the next rebalance
        # round (or an operator) can retry. Best-effort: a failure here is
        # logged and the messages are lost (no further place to stash them).
        for m in failed:
            try:
                await self._registry.agent_store.send_inbox(
                    dead_agent_id,
                    sender=m.get("from", "unknown"),
                    message=m.get("message", ""),
                )
            except Exception as e:
                logger.error(
                    "Re-queue to %s failed; message lost: %s",
                    dead_agent_id, e,
                )

        logger.info(
            "Rebalanced %d/%d tasks from %s across %d survivors (%d failed)",
            moved, len(messages), dead_agent_id, len(candidates), len(failed),
        )
        return moved
