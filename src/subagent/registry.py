"""SubAgentRegistry — tracks active sub-agents and their asyncio tasks."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from langgraph.store.base import BaseStore

from .state import AgentInfo, SubAgentState
from .store import AgentStore

logger = logging.getLogger(__name__)


class SubAgentRegistry:
    """Registry of active sub-agents.

    Tracks AgentInfo (state, cost, iteration) and the backing asyncio.Task
    for each sub-agent. Also wraps an AgentStore for BaseStore communication.

    NOT thread-safe. Call from a single asyncio event loop only (master agent
    + HealthMonitor background task). Cooperative concurrency makes the
    two-dict-write race in register()/deregister() unobservable as long as
    there are no awaits between the dict mutations.
    """

    def __init__(self, store: BaseStore):
        self._store = store
        self._agent_store = AgentStore(store)
        self._agents: dict[str, AgentInfo] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    @property
    def agent_store(self) -> AgentStore:
        return self._agent_store

    def register(self, info: AgentInfo, task: asyncio.Task) -> None:
        """Register a new sub-agent and its backing task."""
        self._agents[info.agent_id] = info
        self._tasks[info.agent_id] = task
        logger.info("Registered sub-agent %s (name=%s, role=%s)", info.agent_id, info.name, info.role)

    def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        return self._agents.get(agent_id)

    def get_task(self, agent_id: str) -> Optional[asyncio.Task]:
        return self._tasks.get(agent_id)

    def list_agents(self) -> list[AgentInfo]:
        return list(self._agents.values())

    def filter_by_state(self, state: SubAgentState) -> list[AgentInfo]:
        return [a for a in self._agents.values() if a.state == state]

    def filter_by_role(self, role: str) -> list[AgentInfo]:
        return [a for a in self._agents.values() if a.role == role]

    def update_state(self, agent_id: str, new_state: SubAgentState) -> None:
        info = self._agents.get(agent_id)
        if info:
            old = info.state
            info.state = new_state
            logger.debug("Sub-agent %s state: %s → %s", agent_id, old, new_state)

    def update_cost(self, agent_id: str, cost_cents: float) -> None:
        info = self._agents.get(agent_id)
        if info:
            info.cost_cents = cost_cents

    def increment_iteration(self, agent_id: str) -> None:
        info = self._agents.get(agent_id)
        if info:
            info.iteration += 1

    async def deregister(self, agent_id: str) -> None:
        """Cancel the agent's task and remove from registry.

        Pops dict entries first so concurrent readers see the agent as gone
        before we start awaiting cancellation. On timeout the task may still
        be running in the background (ignoring cancellation) — we log and
        abandon it rather than hanging forever.
        """
        task = self._tasks.pop(agent_id, None)
        info = self._agents.pop(agent_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "Sub-agent %s task did not cancel within 5s; abandoning",
                    agent_id,
                )
            except asyncio.CancelledError:
                pass
        if info:
            logger.info("Deregistered sub-agent %s", agent_id)

    async def shutdown_all(self) -> None:
        """Cancel all registered sub-agents. Called at platform shutdown.

        Deregisters every active agent in parallel so the platform can exit
        without leaving orphan coroutines. Safe to call with an empty registry.
        """
        agent_ids = list(self._agents.keys())
        if not agent_ids:
            return
        logger.info("Shutting down %d sub-agents", len(agent_ids))
        await asyncio.gather(
            *(self.deregister(agent_id) for agent_id in agent_ids),
            return_exceptions=True,
        )

    async def sync_from_store(self) -> None:
        """Pull heartbeat + iteration from BaseStore into AgentInfo.

        Sub-agents write heartbeats to BaseStore via ``AgentStore.write_heartbeat``
        (the source of truth for liveness). HealthMonitor reads from AgentInfo
        (in-memory). This method bridges the two — call it before
        ``HealthMonitor.check_all()`` to refresh AgentInfo from the store.

        Safe to call with an empty registry. Reads are best-effort: if a read
        fails, the corresponding AgentInfo is left unchanged and a debug log
        is emitted.
        """
        for agent_id, info in list(self._agents.items()):
            try:
                hb = await self._agent_store.read_heartbeat(agent_id)
            except Exception as e:
                logger.debug("sync_from_store: heartbeat read failed for %s: %s", agent_id, e)
                continue
            if hb:
                ts = hb.get("timestamp")
                if isinstance(ts, (int, float)):
                    info.last_heartbeat = float(ts)
                itr = hb.get("iteration")
                if isinstance(itr, int):
                    info.iteration = itr
