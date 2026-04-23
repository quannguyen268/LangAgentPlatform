"""RecoveryExecutor — carry out RecoveryChain decisions.

Bridges the gap between ``RecoveryChain.decide_action()`` (pure decision logic)
and actually performing the retry / escalate / reassign / abort.
"""
from __future__ import annotations

import logging

from .broadcaster import EventBroadcaster
from .context_recovery import build_recovery_context
from .recovery import RecoveryAction, RecoveryChain, next_tier
from .registry import SubAgentRegistry
from .state import AgentInfo, SubAgentState

logger = logging.getLogger(__name__)


class RecoveryExecutor:
    """Execute recovery actions decided by RecoveryChain."""

    def __init__(
        self,
        registry: SubAgentRegistry,
        chain: RecoveryChain,
        spawner,
        broadcaster: EventBroadcaster,
    ):
        self._registry = registry
        self._chain = chain
        self._spawner = spawner
        self._broadcaster = broadcaster

    async def handle_failure(self, agent_id: str, reason: str) -> None:
        """Decide + perform recovery for a failed agent."""
        info = self._registry.get_agent(agent_id)
        if info is None:
            return
        action = self._chain.decide_action(info)
        logger.info("Recovery: agent=%s reason=%s → %s", agent_id, reason, action.value)
        self._broadcaster.agent_failed(agent_id=agent_id, reason=reason, action=action.value)

        if action == RecoveryAction.RETRY:
            await self._respawn(info, recovery=True)
        elif action == RecoveryAction.ESCALATE:
            higher = next_tier(info.tier)
            if higher:
                info.tier = higher
            await self._respawn(info, recovery=True)
        elif action == RecoveryAction.REASSIGN:
            # Phase 2A treats REASSIGN like RETRY with role annotation. Phase 2B
            # will introduce actual cross-role reassignment via team templates.
            await self._respawn(info, recovery=True)
        elif action == RecoveryAction.ABORT:
            await self._abort(info)

    async def _respawn(self, info: AgentInfo, *, recovery: bool) -> None:
        """Cancel the old task, build a recovery context, and spawn a new one."""
        # Cancel the old task without fully deregistering — keep AgentInfo around
        old_task = self._registry.get_task(info.agent_id)
        if old_task and not old_task.done():
            old_task.cancel()

        info.retry_count += 1
        info.state = SubAgentState.SPAWNING
        info.error = None

        context = None
        if recovery:
            context = await build_recovery_context(
                agent_id=info.agent_id,
                role=info.role,
                store=self._registry._store,
            )

        new_task = await self._spawner.spawn(info, recovery_context=context)
        self._registry._tasks[info.agent_id] = new_task

    async def _abort(self, info: AgentInfo) -> None:
        info.state = SubAgentState.FAILED
        await self._registry.deregister(info.agent_id)
